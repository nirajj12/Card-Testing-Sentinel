import asyncio
import sqlite3
from datetime import UTC, datetime, timedelta

from card_testing_sentinel.api.contracts import PrecheckRequest
from card_testing_sentinel.domain.events import LifecycleEvent
from card_testing_sentinel.domain.exceptions import RuntimeStateError
from card_testing_sentinel.persistence.sqlite_repository import SQLiteStateRepository
from card_testing_sentinel.security.identifiers import IdentifierProtector
from card_testing_sentinel.services.risk_service import RiskService


def _service(registry, path, secret="restart-secret-012345678901"):
    return RiskService(
        registry, SQLiteStateRepository(path), IdentifierProtector.from_secret(secret)
    )


def test_restart_recovers_decision_state_and_hides_raw_identifiers(tmp_path, registry):
    path = tmp_path / "live.sqlite3"
    first = _service(registry, path)
    ts = datetime(2032, 1, 1, tzinfo=UTC)
    request = PrecheckRequest(
        request_id="restart-request",
        event_id="restart-precheck",
        merchant_id="raw-merchant-sensitive",
        device_id="raw-device-sensitive",
        session_id="raw-session-sensitive",
        ip_reference="203.0.113.44",
        amount=3.0,
        currency="USD",
        campaign_active=False,
        timestamp=ts,
        event_sequence=1,
    )
    decision = asyncio.run(first.precheck(request))
    asyncio.run(
        first.trusted_gateway_outcome(
            event_id="restart-outcome",
            request_id=request.request_id,
            timestamp=ts + timedelta(seconds=1),
            authorization_result="declined",
            failure_reason="generic_decline",
            payment_method="card",
            card_last4="4242",
            card_network="visa",
        )
    )
    first.close()

    second = _service(registry, path)
    recovered = asyncio.run(second.precheck(request))
    assert recovered.idempotent_replay is True
    assert recovered.decision == decision.decision
    assert recovered.device_state_version == decision.device_state_version
    assert second.timeline(request.device_id)[0]["decision"] == decision.decision
    status = second.repository.status()
    assert status["wal_mode"] is True and status["integrity"] == "ok"

    later = PrecheckRequest(
        request_id="restart-request-2",
        event_id="restart-precheck-2",
        merchant_id="raw-merchant-sensitive",
        device_id="raw-device-sensitive",
        session_id="raw-session-sensitive",
        ip_reference="203.0.113.44",
        amount=3.0,
        currency="USD",
        campaign_active=False,
        timestamp=ts + timedelta(seconds=2),
        event_sequence=3,
    )
    snapshot = second.engine.snapshot(
        LifecycleEvent.model_validate(second._request_payload(later))
    )
    assert snapshot["recent_failures_24h"] == 1.0
    assert snapshot["distinct_card_last4_7d"] == 1.0
    assert snapshot["card_diversity_ratio_7d"] == 0.5

    connection = sqlite3.connect(path)
    text = " ".join(
        str(value)
        for table in ("requests", "lifecycle_events")
        for row in connection.execute(f"SELECT * FROM {table}").fetchall()
        for value in row
    )
    connection.close()
    for raw in ("203.0.113.44", "raw-device-sensitive", "raw-merchant-sensitive"):
        assert raw not in text


def test_incompatible_schema_version_is_refused(tmp_path, registry):
    path = tmp_path / "old.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript(
        "CREATE TABLE runtime_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);"
        "INSERT INTO runtime_metadata VALUES ('schema_version', 'old-schema-1');"
    )
    connection.commit()
    connection.close()
    try:
        SQLiteStateRepository(path).initialize()
    except RuntimeStateError as error:
        assert "incompatible schema" in str(error)
    else:  # pragma: no cover
        raise AssertionError("expected an incompatible-schema refusal")
