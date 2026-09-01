import json
import sqlite3

import pytest

from card_testing_sentinel.domain.exceptions import DuplicateConflictError
from card_testing_sentinel.persistence.models import (
    StoredEvent,
    StoredGatewayOrder,
    StoredGatewayPayment,
    StoredRequest,
    StoredWebhookDelivery,
)
from card_testing_sentinel.persistence.sqlite_repository import (
    SQLiteStateRepository,
)


def _request() -> StoredRequest:
    return StoredRequest(
        request_id="request-1",
        event_id="event-1",
        merchant_hash="hmac_merchant_a",
        customer_hash=None,
        device_hash="hmac_device_a",
        session_hash="hmac_session_a",
        ip_hash="hmac_ip_a",
        timestamp="2030-01-01T00:00:00+00:00",
        event_sequence=1,
        payload_digest="digest",
        payload_json=json.dumps({"safe": True}),
        decision="allow",
        risk_score=None,
        rule_score=0,
        reason_codes_json="[]",
        state_version=1,
        response_json="{}",
        latency_ms=1.0,
    )


def test_sqlite_initializes_wal_foreign_keys_and_constraints(tmp_path):
    repository = SQLiteStateRepository(tmp_path / "state.sqlite3")
    repository.initialize()
    assert repository.status()["wal_mode"] is True
    repository.save_request(_request())
    with pytest.raises(DuplicateConflictError):
        repository.save_request(_request())
    connection = sqlite3.connect(repository.path)
    assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    connection.close()


def test_sqlite_event_foreign_key_and_unique_transition(tmp_path):
    repository = SQLiteStateRepository(tmp_path / "state.sqlite3")
    repository.initialize()
    repository.save_request(_request())
    event = StoredEvent(
        event_id="outcome-1",
        request_id="request-1",
        event_type="authorization_outcome",
        device_hash="hmac_device_a",
        session_hash="hmac_session_a",
        timestamp="2030-01-01T00:00:01+00:00",
        event_sequence=2,
        payload_digest="outcome-digest",
        payload_json=json.dumps({"authorization_result": "approved"}),
        state_version=2,
    )
    repository.save_event(event)
    with pytest.raises(DuplicateConflictError):
        repository.save_event(StoredEvent(**{**event.__dict__, "event_id": "other"}))
    assert repository.get_event("outcome-1") == event


def test_sqlite_persists_multiple_payments_and_webhook_delivery_ids(tmp_path):
    repository = SQLiteStateRepository(tmp_path / "gateway.sqlite3")
    repository.initialize()
    repository.save_request(_request())
    order = StoredGatewayOrder(
        sentinel_request_id="request-1",
        razorpay_order_id="order_test_1",
        amount_minor=200,
        currency="INR",
        receipt="receipt-1",
        status="created",
    )
    repository.save_gateway_order(order)
    repository.save_gateway_payment(
        StoredGatewayPayment(
            "pay_failed", "order_test_1", "request-1", "failed", False, True
        )
    )
    repository.save_gateway_payment(
        StoredGatewayPayment(
            "pay_captured",
            "order_test_1",
            "request-1",
            "captured",
            True,
            True,
            "recorded_approved",
        )
    )
    delivery = StoredWebhookDelivery("evt-1", "digest-1", "payment.captured")
    repository.save_webhook_delivery(delivery)
    assert len(repository.gateway_payments_for_order("order_test_1")) == 2
    assert repository.get_webhook_delivery("evt-1") == delivery
