import asyncio
import sqlite3
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from card_testing_sentinel.api.contracts import OutcomeRequest, PrecheckRequest
from card_testing_sentinel.persistence.sqlite_repository import (
    SQLiteStateRepository,
)
from card_testing_sentinel.security.identifiers import IdentifierProtector
from card_testing_sentinel.services.fraud_detection import FraudDetectionService


def _registry(registry):
    return SimpleNamespace(
        scorer=registry.scorer,
        policy=registry.policy,
        model_version=registry.model_version,
        policy_version=registry.policy_version,
    )


def test_restart_recovers_decision_state_version_and_hides_raw_identifiers(
    tmp_path, registry
):
    path = tmp_path / "live.sqlite3"
    protector = IdentifierProtector.from_secret("restart-secret-012345678901")
    first = FraudDetectionService(
        _registry(registry), SQLiteStateRepository(path), protector
    )
    timestamp = datetime(2032, 1, 1, tzinfo=UTC)
    request = PrecheckRequest(
        request_id="restart-request",
        event_id="restart-precheck",
        device_id="raw-device-sensitive",
        session_id="raw-session-sensitive",
        card_reference="raw-gateway-card-token",
        card_bin="410000",
        ip_reference="203.0.113.44",
        amount=3.0,
        currency="USD",
        timestamp=timestamp,
        event_sequence=1,
        campaign_active=False,
    )
    decision = asyncio.run(first.precheck(request))
    if decision.decision != "block":
        asyncio.run(
            first.outcome(
                OutcomeRequest(
                    event_id="restart-outcome",
                    request_id=request.request_id,
                    device_id=request.device_id,
                    session_id=request.session_id,
                    timestamp=timestamp + timedelta(seconds=1),
                    event_sequence=2,
                    authorization_result="declined",
                    decline_reason="generic_decline",
                )
            )
        )
    first.close()

    second = FraudDetectionService(
        _registry(registry), SQLiteStateRepository(path), protector
    )
    recovered = asyncio.run(second.precheck(request))
    assert recovered.idempotent_replay is True
    assert recovered.decision == decision.decision
    assert recovered.device_state_version == decision.device_state_version
    assert second.model_score_calls == 0
    assert second.timeline(request.device_id)[0]["decision"] == decision.decision
    status = second.repository.status()
    assert status["wal_mode"] is True
    assert status["integrity"] == "ok"

    connection = sqlite3.connect(path)
    database_text = " ".join(
        str(value)
        for table in ("requests", "lifecycle_events")
        for row in connection.execute(f"SELECT * FROM {table}").fetchall()
        for value in row
    )
    connection.close()
    assert "raw-gateway-card-token" not in database_text
    assert "203.0.113.44" not in database_text
    assert "raw-device-sensitive" not in database_text
