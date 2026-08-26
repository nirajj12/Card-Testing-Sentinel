import json
import sqlite3

import pytest

from card_testing_sentinel.domain.exceptions import DuplicateConflictError
from card_testing_sentinel.persistence.models import StoredEvent, StoredRequest
from card_testing_sentinel.persistence.sqlite_repository import (
    SQLiteStateRepository,
)


def _request() -> StoredRequest:
    return StoredRequest(
        request_id="request-1",
        event_id="event-1",
        device_hash="hmac_device_a",
        session_hash="hmac_session_a",
        ip_hash="hmac_ip_a",
        card_hash="hmac_card_a",
        timestamp="2030-01-01T00:00:00+00:00",
        event_sequence=1,
        payload_digest="digest",
        payload_json=json.dumps({"safe": True}),
        decision="allow",
        raw_score=0.1,
        risk_score=0.2,
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
    assert repository.latest_order() == (event.timestamp, 2)
