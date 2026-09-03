from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

from card_testing_sentinel.api.contracts import PrecheckRequest
from card_testing_sentinel.domain.events import LifecycleEvent
from card_testing_sentinel.services.razorpay import (
    RazorpayCheckoutService,
    RazorpayClient,
    RazorpayCredentials,
)
from tests.helpers import precheck_payload

WEBHOOK_SECRET = "server-only-webhook-secret"


class FakeRazorpayClient(RazorpayClient):
    def __init__(self):
        super().__init__(
            RazorpayCredentials("rzp_test_webhook_public", "checkout-secret")
        )
        self.number = 0

    async def create_order(self, payload: dict) -> dict:
        self.number += 1
        return {
            "id": f"order_webhook_{self.number}",
            "status": "created",
            "amount": payload["amount"],
            "currency": payload["currency"],
        }


def _install(client) -> None:
    runtime = client.app.state.runtime
    runtime.razorpay = RazorpayCheckoutService(
        client=FakeRazorpayClient(),
        repository=runtime.service.repository,
        risk_service=runtime.service,
        protector=runtime.service.protector,
        webhook_secret=WEBHOOK_SECRET,
    )


def _allowed_order(client, index: int = 1, *, base=None) -> tuple[dict, dict]:
    precheck = precheck_payload(index, base=base, amount=100.0)
    decision = client.post("/api/precheck", json=precheck)
    assert decision.status_code == 200
    assert decision.json()["decision"] == "allow"
    order = client.post(
        "/api/razorpay/orders",
        json={
            "sentinel_request_id": precheck["request_id"],
            "device_id": precheck["device_id"],
            "session_id": precheck["session_id"],
        },
    )
    assert order.status_code == 200
    return precheck, order.json()


def _body(
    event: str, order_id: str, payment_id: str, *, payment_fields: dict | None = None
) -> bytes:
    payment = {
        "id": payment_id,
        "order_id": order_id,
        "status": event.split(".")[-1],
    }
    payment.update(payment_fields or {})
    return json.dumps(
        {
            "event": event,
            "payload": {
                "payment": {"entity": payment},
                "order": {"entity": {"id": order_id}},
            },
        },
        separators=(",", ":"),
    ).encode()


def _card(last4: str, *, network: str = "Visa") -> dict:
    return {
        "method": "card",
        "international": False,
        "card": {
            "last4": last4,
            "network": network,
            "type": "debit",
            "issuer": "Test Bank",
            "international": False,
        },
    }


def _send(client, event_id: str, body: bytes, *, valid: bool = True):
    signature = hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    if not valid:
        signature = "0" * 64
    return client.post(
        "/api/webhooks/razorpay",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Razorpay-Signature": signature,
            "x-razorpay-event-id": event_id,
        },
    )


def test_invalid_signature_mutates_nothing(client):
    _install(client)
    _, order = _allowed_order(client, base=datetime.now(UTC) - timedelta(minutes=2))
    body = _body(
        "payment.failed",
        order["razorpay_order_id"],
        "pay_invalid",
        payment_fields=_card("9999"),
    )
    response = _send(client, "evt-invalid", body, valid=False)
    assert response.status_code == 400
    repository = client.app.state.runtime.service.repository
    assert repository.get_gateway_payment("pay_invalid") is None
    assert repository.get_webhook_delivery("evt-invalid") is None
    assert not repository.events


def test_failed_webhook_is_deduplicated_and_enters_next_feature_snapshot(client):
    _install(client)
    base = datetime.now(UTC) - timedelta(minutes=2)
    service = client.app.state.runtime.service
    initial_request = PrecheckRequest.model_validate(precheck_payload(1, base=base))
    initial_snapshot = service.engine.snapshot(
        LifecycleEvent.model_validate(service._request_payload(initial_request))
    )
    assert initial_snapshot["distinct_card_last4_7d"] == 0.0
    assert initial_snapshot["distinct_card_networks_7d"] == 0.0
    first_request, order = _allowed_order(client, base=base)
    repository = service.repository
    original_evidence = repository.get_request(
        first_request["request_id"]
    ).evidence_json
    body = _body(
        "payment.failed",
        order["razorpay_order_id"],
        "pay_failed_1",
        payment_fields={**_card("1111"), "error_reason": "insufficient_funds"},
    )
    first = _send(client, "evt-failed-1", body)
    duplicate = _send(client, "evt-failed-1", body)
    assert first.status_code == 200
    assert first.json()["history_status"] == "recorded_declined"
    assert duplicate.json()["duplicate"] is True
    assert repository.get_gateway_payment("pay_failed_1").status == "failed"
    assert len(repository.events) == 1
    outcome = json.loads(next(iter(repository.events.values())).payload_json)
    assert set(outcome) == {
        "event_id",
        "request_id",
        "event_sequence",
        "timestamp",
        "event_type",
        "device_id",
        "session_id",
        "authorization_result",
        "failure_reason",
        "payment_method",
        "card_last4",
        "card_network",
        "card_type",
        "card_issuer",
        "international",
    }
    expected_metadata = {
        "authorization_result": "declined",
        "failure_reason": "insufficient_funds",
        "payment_method": "card",
        "card_last4": "1111",
        "card_network": "visa",
        "card_type": "debit",
        "card_issuer": "Test Bank",
        "international": False,
    }
    assert {key: outcome[key] for key in expected_metadata} == expected_metadata
    assert (
        repository.get_request(first_request["request_id"]).evidence_json
        == original_evidence
    )

    next_request = precheck_payload(2, base=datetime.now(UTC))
    next_event = LifecycleEvent.model_validate(
        service._request_payload(PrecheckRequest.model_validate(next_request))
    )
    next_snapshot = service.engine.snapshot(next_event)
    assert next_snapshot["distinct_card_last4_7d"] == 1.0
    assert next_snapshot["distinct_card_networks_7d"] == 1.0
    next_response = client.post("/api/precheck", json=next_request)
    assert next_response.status_code == 200
    stored = repository.get_request(next_request["request_id"])
    evidence = json.loads(stored.evidence_json)
    assert evidence["recent_failures_24h"] == 1.0
    assert evidence["decline_streak"] == 1.0


def test_three_sequential_signed_failures_are_visible_to_the_next_precheck(client):
    _install(client)
    anchor = datetime.now(UTC) - timedelta(hours=1)
    repository = client.app.state.runtime.service.repository
    orders = []
    for index in range(1, 4):
        request = precheck_payload(index, base=anchor, amount=100.0)
        request["timestamp"] = (anchor + timedelta(minutes=index * 5)).isoformat()
        decision = client.post("/api/precheck", json=request)
        assert decision.status_code == 200
        # The test never changes the policy result. An order is possible only
        # while the genuine frozen policy returns ALLOW.
        assert decision.json()["decision"] == "allow"
        order_response = client.post(
            "/api/razorpay/orders",
            json={
                "sentinel_request_id": request["request_id"],
                "device_id": request["device_id"],
                "session_id": request["session_id"],
            },
        )
        assert order_response.status_code == 200
        orders.append(order_response.json())

    for index, order in enumerate(orders, start=1):
        failure = _send(
            client,
            f"evt-sequential-{index}",
            _body(
                "payment.failed",
                order["razorpay_order_id"],
                f"pay_sequential_{index}",
                payment_fields=_card(f"{index}{index}{index}{index}"),
            ),
        )
        assert failure.status_code == 200

    activity = repository.recent_activity(10)
    razorpay_attempts = [row for row in activity if row["source"] == "razorpay_test"]
    assert len(razorpay_attempts) == 3
    assert len({row["id"] for row in razorpay_attempts}) == 3
    assert all(row["payment_attempt_count"] == 1 for row in razorpay_attempts)
    assert all(
        row["history_status"] == "recorded_declined" for row in razorpay_attempts
    )

    fourth = precheck_payload(4, base=anchor, amount=100.0)
    fourth["timestamp"] = (datetime.now(UTC) + timedelta(minutes=1)).isoformat()
    service = client.app.state.runtime.service
    event = LifecycleEvent.model_validate(
        service._request_payload(PrecheckRequest.model_validate(fourth))
    )
    snapshot = service.engine.snapshot(event)
    assert snapshot["distinct_card_last4_7d"] == 3.0
    assert snapshot["distinct_card_networks_7d"] == 1.0
    assert snapshot["card_change_after_decline_7d"] == 2.0
    assert snapshot["card_diversity_ratio_7d"] == 0.75
    assert snapshot["card_change_after_decline_ratio_7d"] == 2.0 / 3.0
    response = client.post("/api/precheck", json=fourth)
    assert response.status_code == 200
    evidence = json.loads(repository.get_request("request-4").evidence_json)
    assert evidence["recent_failures_24h"] == 3.0
    assert evidence["decline_streak"] == 3.0


def test_authorized_then_captured_then_paid_advances_without_duplicates(client):
    _install(client)
    _, order = _allowed_order(client, base=datetime.now(UTC) - timedelta(minutes=2))
    order_id = order["razorpay_order_id"]
    payment_id = "pay_advance"
    authorized = _send(
        client, "evt-authorized", _body("payment.authorized", order_id, payment_id)
    )
    assert authorized.json()["payment_status"] == "authorized"
    assert authorized.json()["history_status"] == "pending"
    captured = _send(
        client,
        "evt-captured",
        _body(
            "payment.captured",
            order_id,
            payment_id,
            payment_fields=_card("4242", network="MasterCard"),
        ),
    )
    assert captured.json()["payment_status"] == "captured"
    assert captured.json()["history_status"] == "recorded_approved"
    paid = _send(client, "evt-paid", _body("order.paid", order_id, payment_id))
    assert paid.json()["payment_status"] == "paid"
    repository = client.app.state.runtime.service.repository
    assert repository.get_gateway_payment(payment_id).status == "paid"
    assert len(repository.events) == 2
    outcome = repository.get_event_for_request("request-1", "authorization_outcome")
    payload = json.loads(outcome.payload_json)
    assert payload["authorization_result"] == "approved"
    assert payload["card_last4"] == "4242"
    assert payload["card_network"] == "mastercard"
    assert payload["payment_method"] == "card"


def test_same_card_retries_do_not_fabricate_card_diversity(client):
    _install(client)
    anchor = datetime.now(UTC) + timedelta(minutes=1)
    for index in range(1, 4):
        request, order = _allowed_order(client, index=index, base=anchor)
        response = _send(
            client,
            f"evt-same-card-{index}",
            _body(
                "payment.failed",
                order["razorpay_order_id"],
                f"pay_same_card_{index}",
                payment_fields=_card("4242"),
            ),
        )
        assert response.status_code == 200
        assert request["device_id"] == "device-demo"

    service = client.app.state.runtime.service
    fourth = PrecheckRequest.model_validate(
        precheck_payload(4, base=anchor, amount=100.0)
    )
    snapshot = service.engine.snapshot(
        LifecycleEvent.model_validate(service._request_payload(fourth))
    )
    assert snapshot["distinct_card_last4_7d"] == 1.0
    assert snapshot["card_change_after_decline_7d"] == 0.0
    assert snapshot["card_diversity_ratio_7d"] == 0.25
    assert snapshot["card_change_after_decline_ratio_7d"] == 0.0


def test_non_card_webhook_ignores_absent_or_malformed_card_metadata(client):
    _install(client)
    _, order = _allowed_order(client, base=datetime.now(UTC) - timedelta(minutes=2))
    response = _send(
        client,
        "evt-upi-failed",
        _body(
            "payment.failed",
            order["razorpay_order_id"],
            "pay_upi_failed",
            payment_fields={"method": "upi", "card": {"last4": "1234"}},
        ),
    )
    assert response.status_code == 200
    repository = client.app.state.runtime.service.repository
    outcome = repository.get_event_for_request("request-1", "authorization_outcome")
    payload = json.loads(outcome.payload_json)
    assert payload["payment_method"] == "upi"
    assert "card_last4" not in payload
    assert "card_network" not in payload


def test_out_of_order_authorized_does_not_regress_captured(client):
    _install(client)
    _, order = _allowed_order(client, base=datetime.now(UTC) - timedelta(minutes=2))
    order_id = order["razorpay_order_id"]
    payment_id = "pay_out_of_order"
    _send(client, "evt-capture-first", _body("payment.captured", order_id, payment_id))
    later = _send(
        client,
        "evt-authorized-late",
        _body("payment.authorized", order_id, payment_id),
    )
    assert later.json()["payment_status"] == "captured"


def test_failed_payment_and_later_payment_id_are_both_preserved(client):
    _install(client)
    _, order = _allowed_order(client, base=datetime.now(UTC) - timedelta(minutes=2))
    order_id = order["razorpay_order_id"]
    _send(client, "evt-first-failed", _body("payment.failed", order_id, "pay_first"))
    later = _send(
        client, "evt-second-captured", _body("payment.captured", order_id, "pay_second")
    )
    assert later.json()["payment_status"] == "captured"
    payments = client.app.state.runtime.service.repository.gateway_payments_for_order(
        order_id
    )
    assert {(row.razorpay_payment_id, row.status) for row in payments} == {
        ("pay_first", "failed"),
        ("pay_second", "captured"),
    }


def test_recent_activity_is_durable_safe_and_separates_source(client):
    _install(client)
    precheck, order = _allowed_order(
        client, base=datetime.now(UTC) - timedelta(minutes=2)
    )
    opened = client.post(
        "/api/razorpay/orders/checkout-opened",
        json={
            "sentinel_request_id": precheck["request_id"],
            "device_id": precheck["device_id"],
            "session_id": precheck["session_id"],
        },
    )
    assert opened.status_code == 200
    _send(
        client,
        "evt-activity-failed",
        _body("payment.failed", order["razorpay_order_id"], "pay_activity"),
    )
    first = client.get("/api/activity/recent").json()["items"]
    second = client.get("/api/activity/recent").json()["items"]
    assert first == second
    item = first[0]
    assert item["source"] == "razorpay_test"
    assert item["sentinel_decision"] == "allow"
    assert item["razorpay_order_created"] is True
    assert item["checkout_opened"] is True
    assert item["razorpay_payment_status"] == "failed"
    assert item["webhook_verified"] is True
    assert item["history_status"] == "recorded_declined"
    assert "request-1" not in json.dumps(item)
    assert "device-demo" not in json.dumps(item)
