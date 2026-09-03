from __future__ import annotations

import hashlib
import hmac
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from card_testing_sentinel.services.razorpay import (
    RazorpayCheckoutService,
    RazorpayClient,
    RazorpayCredentials,
)
from tests.helpers import precheck_payload


class FakeRazorpayClient(RazorpayClient):
    def __init__(self):
        super().__init__(
            RazorpayCredentials(
                key_id="rzp_test_public_for_tests",
                key_secret="server-only-test-secret",
            )
        )
        self.create_calls = 0

    async def create_order(self, payload: dict) -> dict:
        self.create_calls += 1
        return {
            "id": "order_test_sentinel_123",
            "status": "created",
            "amount": payload["amount"],
            "currency": payload["currency"],
        }


def _install_fake(client) -> FakeRazorpayClient:
    runtime = client.app.state.runtime
    fake = FakeRazorpayClient()
    runtime.razorpay = RazorpayCheckoutService(
        client=fake,
        repository=runtime.service.repository,
        risk_service=runtime.service,
        protector=runtime.service.protector,
        webhook_secret="test-webhook-secret",
    )
    return fake


def _order_payload(precheck: dict) -> dict:
    return {
        "sentinel_request_id": precheck["request_id"],
        "device_id": precheck["device_id"],
        "session_id": precheck["session_id"],
    }


def test_allow_creates_one_server_side_test_order_and_exposes_no_secret(client):
    fake = _install_fake(client)
    precheck = precheck_payload(
        base=datetime.now(UTC) - timedelta(minutes=1), amount=100.0
    )
    decision = client.post("/api/precheck", json=precheck).json()
    assert decision["decision"] == "allow"

    first = client.post("/api/razorpay/orders", json=_order_payload(precheck))
    assert first.status_code == 200
    body = first.json()
    assert body["key_id"] == "rzp_test_public_for_tests"
    assert body["test_mode"] is True
    assert body["amount"] == 10000
    assert "secret" not in str(body).lower()

    second = client.post("/api/razorpay/orders", json=_order_payload(precheck))
    assert second.status_code == 200
    assert second.json()["idempotent_replay"] is True
    assert fake.create_calls == 1


def test_payment_signature_is_verified_without_claiming_capture(client):
    fake = _install_fake(client)
    precheck = precheck_payload(
        base=datetime.now(UTC) - timedelta(minutes=1), amount=100.0
    )
    client.post("/api/precheck", json=precheck)
    order = client.post("/api/razorpay/orders", json=_order_payload(precheck)).json()
    payment_id = "pay_test_sentinel_123"
    signature = hmac.new(
        fake.credentials.key_secret.encode(),
        f"{order['razorpay_order_id']}|{payment_id}".encode(),
        hashlib.sha256,
    ).hexdigest()
    payload = {
        **_order_payload(precheck),
        "razorpay_order_id": order["razorpay_order_id"],
        "razorpay_payment_id": payment_id,
        "razorpay_signature": signature,
    }

    verified = client.post("/api/razorpay/payments/verify", json=payload)
    assert verified.status_code == 200
    assert verified.json()["verified"] is True
    assert verified.json()["payment_status"] == "signature_verified"
    assert verified.json()["outcome_recorded"] is False
    assert verified.json()["checkout_recorded"] is False
    assert len(client.app.state.runtime.service.repository.events) == 0

    retry = client.post("/api/razorpay/payments/verify", json=payload)
    assert retry.status_code == 200
    assert retry.json()["idempotent_replay"] is True
    assert len(client.app.state.runtime.service.repository.events) == 0


def test_invalid_signature_records_nothing(client):
    _install_fake(client)
    precheck = precheck_payload(
        base=datetime.now(UTC) - timedelta(minutes=1), amount=100.0
    )
    client.post("/api/precheck", json=precheck)
    order = client.post("/api/razorpay/orders", json=_order_payload(precheck)).json()
    response = client.post(
        "/api/razorpay/payments/verify",
        json={
            **_order_payload(precheck),
            "razorpay_order_id": order["razorpay_order_id"],
            "razorpay_payment_id": "pay_untrusted",
            "razorpay_signature": "0" * 64,
        },
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_payment_signature"
    assert not client.app.state.runtime.service.repository.events


@pytest.mark.parametrize("decision", ["review", "block"])
def test_review_or_block_decision_cannot_create_order(client, decision):
    fake = _install_fake(client)
    precheck = precheck_payload(base=datetime.now(UTC) - timedelta(minutes=1))
    client.post("/api/precheck", json=precheck)
    repository = client.app.state.runtime.service.repository
    stored = repository.requests[precheck["request_id"]]
    repository.requests[precheck["request_id"]] = replace(stored, decision=decision)

    response = client.post("/api/razorpay/orders", json=_order_payload(precheck))
    assert response.status_code == 409
    assert response.json()["error"] == "payment_order_not_allowed"
    assert fake.create_calls == 0
