"""Isolated in-memory repository for tests and demo sessions."""

from __future__ import annotations

import json

from card_testing_sentinel.domain.exceptions import DuplicateConflictError
from card_testing_sentinel.persistence.models import (
    StoredEvent,
    StoredGatewayOrder,
    StoredGatewayPayment,
    StoredRequest,
    StoredWebhookDelivery,
)


class InMemoryStateRepository:
    store_type = "memory"

    def __init__(self) -> None:
        self.requests: dict[str, StoredRequest] = {}
        self.request_events: dict[str, StoredRequest] = {}
        self.events: dict[str, StoredEvent] = {}
        self.gateway_orders: dict[str, StoredGatewayOrder] = {}
        self.gateway_order_ids: dict[str, StoredGatewayOrder] = {}
        self.gateway_payments: dict[str, StoredGatewayPayment] = {}
        self.webhook_deliveries: dict[str, StoredWebhookDelivery] = {}
        self.initialized = False

    def initialize(self) -> None:
        self.initialized = True

    def close(self) -> None:
        self.initialized = False

    def get_request(self, request_id: str) -> StoredRequest | None:
        return self.requests.get(request_id)

    def get_request_by_event(self, event_id: str) -> StoredRequest | None:
        return self.request_events.get(event_id)

    def get_event(self, event_id: str) -> StoredEvent | None:
        return self.events.get(event_id)

    def get_event_for_request(
        self, request_id: str, event_type: str
    ) -> StoredEvent | None:
        return next(
            (
                event
                for event in self.events.values()
                if event.request_id == request_id and event.event_type == event_type
            ),
            None,
        )

    def save_request(self, request: StoredRequest) -> None:
        if (
            request.request_id in self.requests
            or request.event_id in self.request_events
        ):
            raise DuplicateConflictError("request identifier already exists")
        self.requests[request.request_id] = request
        self.request_events[request.event_id] = request

    def save_event(self, event: StoredEvent) -> None:
        if event.event_id in self.events:
            raise DuplicateConflictError("event identifier already exists")
        if self.get_event_for_request(event.request_id, event.event_type):
            raise DuplicateConflictError("lifecycle transition already exists")
        self.events[event.event_id] = event

    def get_gateway_order(self, sentinel_request_id: str) -> StoredGatewayOrder | None:
        return self.gateway_orders.get(sentinel_request_id)

    def get_gateway_order_by_id(
        self, razorpay_order_id: str
    ) -> StoredGatewayOrder | None:
        return self.gateway_order_ids.get(razorpay_order_id)

    def save_gateway_order(self, order: StoredGatewayOrder) -> None:
        existing = self.gateway_orders.get(order.sentinel_request_id)
        if existing is not None:
            if existing != order:
                raise DuplicateConflictError("gateway order already exists")
            return
        if order.razorpay_order_id in self.gateway_order_ids:
            raise DuplicateConflictError("Razorpay order identifier already exists")
        self.gateway_orders[order.sentinel_request_id] = order
        self.gateway_order_ids[order.razorpay_order_id] = order

    def mark_gateway_checkout_opened(self, razorpay_order_id: str) -> None:
        order = self.gateway_order_ids.get(razorpay_order_id)
        if order is None:
            raise DuplicateConflictError("gateway order does not exist")
        updated = StoredGatewayOrder(**{**order.__dict__, "checkout_opened": True})
        self.gateway_orders[order.sentinel_request_id] = updated
        self.gateway_order_ids[razorpay_order_id] = updated

    def update_gateway_order_status(self, razorpay_order_id: str, status: str) -> None:
        order = self.gateway_order_ids.get(razorpay_order_id)
        if order is None:
            raise DuplicateConflictError("gateway order does not exist")
        updated = StoredGatewayOrder(**{**order.__dict__, "status": status})
        self.gateway_orders[order.sentinel_request_id] = updated
        self.gateway_order_ids[razorpay_order_id] = updated

    def get_gateway_payment(
        self, razorpay_payment_id: str
    ) -> StoredGatewayPayment | None:
        return self.gateway_payments.get(razorpay_payment_id)

    def save_gateway_payment(self, payment: StoredGatewayPayment) -> None:
        existing = self.gateway_payments.get(payment.razorpay_payment_id)
        if existing is not None:
            if (
                existing.razorpay_order_id != payment.razorpay_order_id
                or existing.sentinel_request_id != payment.sentinel_request_id
            ):
                raise DuplicateConflictError("gateway payment already exists")
            self.gateway_payments[payment.razorpay_payment_id] = payment
            return
        self.gateway_payments[payment.razorpay_payment_id] = payment

    def gateway_payments_for_order(
        self, razorpay_order_id: str
    ) -> list[StoredGatewayPayment]:
        return [
            row
            for row in self.gateway_payments.values()
            if row.razorpay_order_id == razorpay_order_id
        ]

    def get_webhook_delivery(self, event_id: str) -> StoredWebhookDelivery | None:
        return self.webhook_deliveries.get(event_id)

    def save_webhook_delivery(self, delivery: StoredWebhookDelivery) -> None:
        existing = self.webhook_deliveries.get(delivery.event_id)
        if existing is not None and existing != delivery:
            raise DuplicateConflictError("webhook event identifier already exists")
        self.webhook_deliveries[delivery.event_id] = delivery

    def recent_activity(self, limit: int) -> list[dict]:
        return [self._activity(row) for row in reversed(self.requests_in_order())][
            :limit
        ]

    def requests_in_order(self) -> list[StoredRequest]:
        return sorted(
            self.requests.values(),
            key=lambda row: (row.timestamp, row.event_sequence),
        )

    def events_in_order(self) -> list[StoredEvent]:
        return sorted(
            self.events.values(),
            key=lambda row: (row.timestamp, row.event_sequence),
        )

    def decisions(self, limit: int) -> list[dict]:
        rows = list(reversed(self.requests_in_order()))[:limit]
        return [self._safe_request(row) for row in rows]

    def device_timeline(self, device_hash: str) -> list[dict]:
        requests = [
            self._safe_request(row)
            for row in self.requests_in_order()
            if row.device_hash == device_hash
        ]
        events = [
            self._safe_event(row)
            for row in self.events_in_order()
            if row.device_hash == device_hash
        ]
        return sorted(
            [*requests, *events],
            key=lambda row: (row["timestamp"], row["event_sequence"]),
        )

    def status(self) -> dict:
        return {
            "type": self.store_type,
            "initialized": self.initialized,
            "requests": len(self.requests),
            "events": len(self.events),
            "journal_mode": "n/a (in-memory, not file-backed)",
            "wal_mode": False,
        }

    def _activity(self, row: StoredRequest) -> dict:
        payload = json.loads(row.payload_json)
        order = self.gateway_orders.get(row.request_id)
        payments = (
            self.gateway_payments_for_order(order.razorpay_order_id) if order else []
        )
        return self._safe_activity(row, payload, order, payments)

    @staticmethod
    def _safe_activity(row, payload, order, payments) -> dict:
        import hashlib

        rank = {
            "paid": 5,
            "captured": 4,
            "authorized": 3,
            "failed": 2,
            "signature_verified": 1,
        }
        payment = max(payments, key=lambda item: rank.get(item.status, 0), default=None)
        source = (
            "replay"
            if row.request_id.startswith(("demo_", "traffic_"))
            else "razorpay_test"
        )
        return {
            "id": hashlib.sha256(row.request_id.encode()).hexdigest()[:20],
            "protected_reference": hashlib.sha256(row.request_id.encode()).hexdigest()[
                :20
            ],
            "timestamp": row.timestamp,
            "amount": float(payload["amount"]),
            "currency": payload["currency"],
            "source": source,
            "sentinel_decision": row.decision,
            "risk_score": row.risk_score,
            "reason_codes": json.loads(row.reason_codes_json),
            "evidence": json.loads(row.evidence_json),
            "razorpay_order_created": order is not None,
            "checkout_opened": bool(order and order.checkout_opened),
            "razorpay_payment_status": payment.status if payment else None,
            "signature_verified": any(item.signature_verified for item in payments),
            "webhook_verified": any(item.webhook_verified for item in payments),
            "history_status": payment.history_status if payment else "not_recorded",
            "payment_attempt_count": len(payments),
        }

    @staticmethod
    def _safe_request(row: StoredRequest) -> dict:
        return {
            "event_id": row.event_id,
            "request_id": row.request_id,
            "event_type": "authorization_request",
            "timestamp": row.timestamp,
            "event_sequence": row.event_sequence,
            "decision": row.decision,
            "risk_score": row.risk_score,
            "rule_score": row.rule_score,
            "reason_codes": json.loads(row.reason_codes_json),
            "state_version": row.state_version,
            "latency_ms": row.latency_ms,
        }

    @staticmethod
    def _safe_event(row: StoredEvent) -> dict:
        payload = json.loads(row.payload_json)
        return {
            "event_id": row.event_id,
            "request_id": row.request_id,
            "event_type": row.event_type,
            "timestamp": row.timestamp,
            "event_sequence": row.event_sequence,
            "authorization_result": payload.get("authorization_result"),
            "state_version": row.state_version,
        }
