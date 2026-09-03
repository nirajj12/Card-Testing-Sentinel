"""Server-only Razorpay Standard Checkout integration.

The key secret is held only by this module. Orders are created only for a
persisted Sentinel ALLOW decision, and payment success is accepted only after
the Checkout signature matches the server-stored order id.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from card_testing_sentinel.domain.exceptions import (
    PaymentGatewayConfigurationError,
    PaymentGatewayError,
    PaymentOrderNotAllowed,
    PaymentSignatureError,
    PaymentWebhookPayloadError,
)
from card_testing_sentinel.persistence.models import (
    StoredGatewayOrder,
    StoredGatewayPayment,
    StoredWebhookDelivery,
)
from card_testing_sentinel.persistence.repository import StateRepository
from card_testing_sentinel.security.identifiers import IdentifierProtector
from card_testing_sentinel.services.risk_service import RiskService

RAZORPAY_ORDERS_URL = "https://api.razorpay.com/v1/orders"
PAYMENT_STATE_TRANSITIONS = {
    "signature_verified": {
        "signature_verified",
        "authorized",
        "failed",
        "captured",
        "paid",
    },
    "authorized": {"authorized", "failed", "captured", "paid"},
    "failed": {"failed", "captured", "paid"},
    "captured": {"captured", "paid"},
    "paid": {"paid"},
}

SUPPORTED_PAYMENT_METHODS = {"card", "upi", "netbanking", "wallet"}
CARD_NETWORKS = {
    "visa": "visa",
    "mastercard": "mastercard",
    "amex": "amex",
    "americanexpress": "amex",
    "rupay": "rupay",
    "diners": "diners",
    "dinersclub": "diners",
}
CARD_TYPES = {"credit", "debit", "prepaid", "unknown"}
FAILURE_REASONS = {
    "generic_decline": "generic_decline",
    "payment_failed": "generic_decline",
    "insufficient_funds": "insufficient_funds",
    "do_not_honor": "do_not_honor",
    "card_declined": "card_declined",
    "authentication_failed": "authentication_failed",
    "international_blocked": "international_blocked",
    "international_transaction_not_allowed": "international_blocked",
}


def _trusted_payment_metadata(payment: dict) -> dict:
    """Project safe, optional history from a signed Razorpay payment entity."""
    method_value = payment.get("method")
    method = (
        method_value.strip().lower()
        if isinstance(method_value, str)
        and method_value.strip().lower() in SUPPORTED_PAYMENT_METHODS
        else None
    )
    metadata: dict = {}
    if method is not None:
        metadata["payment_method"] = method

    card_value = payment.get("card")
    card = card_value if method == "card" and isinstance(card_value, dict) else {}
    last4 = card.get("last4")
    if (
        isinstance(last4, str)
        and len(last4) == 4
        and last4.isascii()
        and last4.isdigit()
    ):
        metadata["card_last4"] = last4

    network_value = card.get("network")
    if isinstance(network_value, str) and network_value.strip():
        network_key = "".join(
            character for character in network_value.lower() if character.isalnum()
        )
        metadata["card_network"] = CARD_NETWORKS.get(network_key, "other")

    type_value = card.get("type")
    if isinstance(type_value, str) and type_value.strip():
        card_type = type_value.strip().lower()
        metadata["card_type"] = card_type if card_type in CARD_TYPES else "unknown"

    issuer_value = card.get("issuer")
    if isinstance(issuer_value, str):
        issuer = issuer_value.strip()
        if 0 < len(issuer) <= 64:
            metadata["card_issuer"] = issuer

    international = payment.get("international")
    if not isinstance(international, bool):
        international = card.get("international")
    if isinstance(international, bool):
        metadata["international"] = international
    return metadata


def _trusted_failure_reason(payment: dict) -> str:
    value = payment.get("error_reason")
    key = value.strip().lower() if isinstance(value, str) else ""
    return FAILURE_REASONS.get(key, "generic_decline")


@dataclass(frozen=True)
class RazorpayCredentials:
    key_id: str
    key_secret: str

    @classmethod
    def from_environment(cls) -> RazorpayCredentials | None:
        key_id = os.environ.get("RAZORPAY_KEY_ID", "").strip()
        key_secret = os.environ.get("RAZORPAY_KEY_SECRET", "").strip()
        if not key_id and not key_secret:
            return None
        if not key_id or not key_secret:
            raise PaymentGatewayConfigurationError(
                "Razorpay Test Mode credentials are incomplete"
            )
        if not key_id.startswith("rzp_test_"):
            raise PaymentGatewayConfigurationError(
                "only Razorpay Test Mode credentials are accepted"
            )
        return cls(key_id=key_id, key_secret=key_secret)


class RazorpayClient:
    def __init__(
        self,
        credentials: RazorpayCredentials,
        *,
        orders_url: str = RAZORPAY_ORDERS_URL,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.credentials = credentials
        self.orders_url = orders_url
        self.timeout_seconds = timeout_seconds

    async def create_order(self, payload: dict) -> dict:
        return await asyncio.to_thread(self._create_order_sync, payload)

    def _create_order_sync(self, payload: dict) -> dict:
        token = base64.b64encode(
            f"{self.credentials.key_id}:{self.credentials.key_secret}".encode()
        ).decode()
        request = urllib.request.Request(
            self.orders_url,
            data=json.dumps(payload, separators=(",", ":")).encode(),
            headers={
                "Authorization": f"Basic {token}",
                "Content-Type": "application/json",
                "User-Agent": "card-testing-sentinel/1.1",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self.timeout_seconds
            ) as response:
                result = json.loads(response.read().decode())
        except urllib.error.HTTPError as error:
            raise PaymentGatewayError(
                f"Razorpay rejected order creation with HTTP {error.code}"
            ) from None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            raise PaymentGatewayError(
                "Razorpay Test Mode order creation is temporarily unavailable"
            ) from None
        if not isinstance(result, dict) or not str(result.get("id", "")).startswith(
            "order_"
        ):
            raise PaymentGatewayError("Razorpay returned an invalid order response")
        return result

    def verify_payment_signature(
        self, *, order_id: str, payment_id: str, received_signature: str
    ) -> bool:
        message = f"{order_id}|{payment_id}".encode()
        expected = hmac.new(
            self.credentials.key_secret.encode(), message, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, received_signature)


class RazorpayCheckoutService:
    def __init__(
        self,
        *,
        client: RazorpayClient | None,
        repository: StateRepository,
        risk_service: RiskService,
        protector: IdentifierProtector,
        webhook_secret: str | None = None,
    ) -> None:
        self.client = client
        self.repository = repository
        self.risk_service = risk_service
        self.protector = protector
        self.webhook_secret = (webhook_secret or "").strip() or None
        self.lock = asyncio.Lock()

    @property
    def configured(self) -> bool:
        return self.client is not None

    @property
    def public_status(self) -> dict:
        return {
            "configured": self.configured,
            "mode": "test" if self.configured else "unavailable",
            "webhook_configured": self.webhook_secret is not None,
        }

    def _require_client(self) -> RazorpayClient:
        if self.client is None:
            raise PaymentGatewayConfigurationError(
                "Razorpay Test Mode is not configured"
            )
        return self.client

    def _stored_request(self, request_id: str, device_id: str, session_id: str):
        stored = self.repository.get_request(request_id)
        if stored is None:
            raise PaymentOrderNotAllowed("Sentinel request does not exist")
        if stored.device_hash != self.protector.protect("device", device_id):
            raise PaymentOrderNotAllowed("device does not match Sentinel request")
        if stored.session_hash != self.protector.protect("session", session_id):
            raise PaymentOrderNotAllowed("session does not match Sentinel request")
        return stored

    async def create_order(
        self, *, request_id: str, device_id: str, session_id: str
    ) -> dict:
        async with self.lock:
            client = self._require_client()
            stored = self._stored_request(request_id, device_id, session_id)
            if stored.decision != "allow":
                raise PaymentOrderNotAllowed(
                    f"Sentinel decision '{stored.decision}' cannot create an order"
                )
            existing = self.repository.get_gateway_order(request_id)
            if existing is not None:
                return self._order_response(existing, client, idempotent_replay=True)

            request_payload = json.loads(stored.payload_json)
            amount_minor = int(
                (Decimal(str(request_payload["amount"])) * Decimal("100")).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP
                )
            )
            currency = str(request_payload["currency"])
            receipt = f"sentinel_{hashlib.sha256(request_id.encode()).hexdigest()[:24]}"
            remote = await client.create_order(
                {
                    "amount": amount_minor,
                    "currency": currency,
                    "receipt": receipt,
                    "notes": {"sentinel_request_id": request_id},
                }
            )
            order = StoredGatewayOrder(
                sentinel_request_id=request_id,
                razorpay_order_id=str(remote["id"]),
                amount_minor=amount_minor,
                currency=currency,
                receipt=receipt,
                status=str(remote.get("status", "created")),
            )
            self.repository.save_gateway_order(order)
            return self._order_response(order, client, idempotent_replay=False)

    async def mark_checkout_opened(
        self, *, request_id: str, device_id: str, session_id: str
    ) -> dict:
        async with self.lock:
            self._stored_request(request_id, device_id, session_id)
            order = self.repository.get_gateway_order(request_id)
            if order is None:
                raise PaymentOrderNotAllowed("Razorpay order does not exist")
            self.repository.mark_gateway_checkout_opened(order.razorpay_order_id)
            return {"recorded": True}

    @staticmethod
    def _order_response(
        order: StoredGatewayOrder,
        client: RazorpayClient,
        *,
        idempotent_replay: bool,
    ) -> dict:
        return {
            "sentinel_request_id": order.sentinel_request_id,
            "razorpay_order_id": order.razorpay_order_id,
            "key_id": client.credentials.key_id,
            "amount": order.amount_minor,
            "currency": order.currency,
            "test_mode": True,
            "idempotent_replay": idempotent_replay,
            "activity_id": hashlib.sha256(
                order.sentinel_request_id.encode()
            ).hexdigest()[:20],
        }

    async def verify_payment(
        self,
        *,
        request_id: str,
        device_id: str,
        session_id: str,
        razorpay_order_id: str,
        razorpay_payment_id: str,
        razorpay_signature: str,
    ) -> dict:
        async with self.lock:
            client = self._require_client()
            stored = self._stored_request(request_id, device_id, session_id)
            order = self.repository.get_gateway_order_by_id(razorpay_order_id)
            if order is None or order.sentinel_request_id != request_id:
                raise PaymentSignatureError("payment does not match a stored order")
            if stored.decision != "allow":
                raise PaymentOrderNotAllowed(
                    "only an allowed Sentinel request can complete payment"
                )
            if not client.verify_payment_signature(
                order_id=order.razorpay_order_id,
                payment_id=razorpay_payment_id,
                received_signature=razorpay_signature,
            ):
                raise PaymentSignatureError("Razorpay payment signature is invalid")

            existing = self.repository.get_gateway_payment(razorpay_payment_id)
            if existing is not None:
                if (
                    existing.razorpay_order_id != order.razorpay_order_id
                    or existing.sentinel_request_id != request_id
                ):
                    raise PaymentSignatureError(
                        "payment identifier belongs to another order"
                    )
                updated = StoredGatewayPayment(
                    **{
                        **existing.__dict__,
                        "signature_verified": True,
                    }
                )
                self.repository.save_gateway_payment(updated)
                return self._payment_response(updated, idempotent_replay=True)

            payment = StoredGatewayPayment(
                razorpay_payment_id=razorpay_payment_id,
                razorpay_order_id=order.razorpay_order_id,
                sentinel_request_id=request_id,
                status="signature_verified",
                signature_verified=True,
            )
            self.repository.save_gateway_payment(payment)
            return self._payment_response(payment, idempotent_replay=False)

    @staticmethod
    def _payment_response(
        payment: StoredGatewayPayment, *, idempotent_replay: bool
    ) -> dict:
        return {
            "verified": True,
            "sentinel_request_id": payment.sentinel_request_id,
            "razorpay_order_id": payment.razorpay_order_id,
            "razorpay_payment_id": payment.razorpay_payment_id,
            "payment_status": payment.status,
            "outcome_recorded": payment.history_status.startswith("recorded"),
            "checkout_recorded": payment.history_status == "recorded_approved",
            "idempotent_replay": idempotent_replay,
            "message": (
                "Checkout signature verified; awaiting authoritative payment state."
            ),
        }

    @staticmethod
    def _advance_payment_state(current: str, incoming: str) -> str:
        allowed = PAYMENT_STATE_TRANSITIONS.get(current, {current})
        return incoming if incoming in allowed else current

    def _verify_webhook_signature(self, raw_body: bytes, signature: str) -> bool:
        if self.webhook_secret is None:
            raise PaymentGatewayConfigurationError(
                "Razorpay webhook verification is not configured"
            )
        expected = hmac.new(
            self.webhook_secret.encode(), raw_body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    async def process_webhook(
        self, *, raw_body: bytes, signature: str, delivery_id: str
    ) -> dict:
        if not signature or not self._verify_webhook_signature(raw_body, signature):
            raise PaymentSignatureError("Razorpay webhook signature is invalid")
        digest = hashlib.sha256(raw_body).hexdigest()
        async with self.lock:
            existing_delivery = self.repository.get_webhook_delivery(delivery_id)
            if existing_delivery is not None:
                if existing_delivery.payload_digest != digest:
                    raise PaymentWebhookPayloadError(
                        "webhook event ID was reused with different content"
                    )
                return {"accepted": True, "duplicate": True}
            try:
                payload = json.loads(raw_body)
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise PaymentWebhookPayloadError(
                    "webhook body is not valid JSON"
                ) from None
            if not isinstance(payload, dict):
                raise PaymentWebhookPayloadError("webhook body must be a JSON object")
            event_type = str(payload.get("event", ""))
            if event_type not in {
                "payment.failed",
                "payment.authorized",
                "payment.captured",
                "order.paid",
            }:
                self.repository.save_webhook_delivery(
                    StoredWebhookDelivery(delivery_id, digest, event_type or "unknown")
                )
                return {"accepted": True, "duplicate": False, "ignored": True}
            result = await self._apply_webhook_event(event_type, payload)
            self.repository.save_webhook_delivery(
                StoredWebhookDelivery(delivery_id, digest, event_type)
            )
            return {"accepted": True, "duplicate": False, **result}

    async def _apply_webhook_event(self, event_type: str, payload: dict) -> dict:
        container = payload.get("payload")
        if not isinstance(container, dict):
            raise PaymentWebhookPayloadError("webhook payload is missing")
        payment_wrapper = container.get("payment") or {}
        order_wrapper = container.get("order") or {}
        payment = (
            payment_wrapper.get("entity") if isinstance(payment_wrapper, dict) else None
        )
        order_entity = (
            order_wrapper.get("entity") if isinstance(order_wrapper, dict) else None
        )
        payment = payment if isinstance(payment, dict) else {}
        order_entity = order_entity if isinstance(order_entity, dict) else {}
        order_id = str(payment.get("order_id") or order_entity.get("id") or "")
        payment_id = str(payment.get("id") or "")
        if not order_id.startswith("order_"):
            raise PaymentWebhookPayloadError(
                "webhook does not contain a Razorpay order ID"
            )
        order = self.repository.get_gateway_order_by_id(order_id)
        if order is None:
            return {"ignored": True, "reason": "unknown_order"}
        incoming = {
            "payment.failed": "failed",
            "payment.authorized": "authorized",
            "payment.captured": "captured",
            "order.paid": "paid",
        }[event_type]
        if event_type == "order.paid":
            self.repository.update_gateway_order_status(order_id, "paid")
        if not payment_id.startswith("pay_"):
            if event_type == "order.paid":
                return {"payment_status": "paid", "history_status": "pending"}
            raise PaymentWebhookPayloadError("webhook does not contain a payment ID")
        existing = self.repository.get_gateway_payment(payment_id)
        if existing is not None and (
            existing.razorpay_order_id != order_id
            or existing.sentinel_request_id != order.sentinel_request_id
        ):
            raise PaymentWebhookPayloadError("payment belongs to another order")
        current = existing.status if existing else "signature_verified"
        status = self._advance_payment_state(current, incoming)
        history_status = existing.history_status if existing else "pending"
        request_row = self.repository.get_request(order.sentinel_request_id)
        if request_row is None:
            raise PaymentWebhookPayloadError("stored Sentinel request is missing")
        request_time = datetime.fromisoformat(request_row.timestamp).astimezone(UTC)
        now = max(datetime.now(UTC), request_time + timedelta(microseconds=1))
        outcome = self.repository.get_event_for_request(
            order.sentinel_request_id, "authorization_outcome"
        )
        trusted_metadata = _trusted_payment_metadata(payment)
        if status == "failed" and outcome is None:
            key = hashlib.sha256(order.sentinel_request_id.encode()).hexdigest()[:24]
            await self.risk_service.trusted_gateway_outcome(
                request_id=order.sentinel_request_id,
                event_id=f"rzp_outcome_{key}",
                timestamp=now,
                authorization_result="declined",
                failure_reason=_trusted_failure_reason(payment),
                **trusted_metadata,
            )
            history_status = "recorded_declined"
        elif status in {"captured", "paid"} and outcome is None:
            key = hashlib.sha256(order.sentinel_request_id.encode()).hexdigest()[:24]
            await self.risk_service.trusted_gateway_outcome(
                request_id=order.sentinel_request_id,
                event_id=f"rzp_outcome_{key}",
                timestamp=now,
                authorization_result="approved",
                **trusted_metadata,
            )
            await self.risk_service.trusted_gateway_checkout(
                request_id=order.sentinel_request_id,
                event_id=f"rzp_checkout_{key}",
                timestamp=now + timedelta(microseconds=1),
            )
            history_status = "recorded_approved"
        elif outcome is not None:
            outcome_payload = json.loads(outcome.payload_json)
            history_status = f"recorded_{outcome_payload['authorization_result']}"
        stored_payment = StoredGatewayPayment(
            razorpay_payment_id=payment_id,
            razorpay_order_id=order_id,
            sentinel_request_id=order.sentinel_request_id,
            status=status,
            signature_verified=bool(existing and existing.signature_verified),
            webhook_verified=True,
            history_status=history_status,
        )
        self.repository.save_gateway_payment(stored_payment)
        return {
            "payment_status": status,
            "history_status": history_status,
        }

    def recent_activity(self, limit: int = 50) -> list[dict]:
        return self.repository.recent_activity(limit)
