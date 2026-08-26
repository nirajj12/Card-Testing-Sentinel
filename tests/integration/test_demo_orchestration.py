"""Stage 4 integration coverage: SQLite-backed demo orchestration driving
the real FraudDetectionService -- no separate scoring path, no separate
repository, and audit history that survives both `reset` and a restart.
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from card_testing_sentinel.api.contracts import PrecheckRequest
from card_testing_sentinel.common.integrity import sha256_file, verify_manifest
from card_testing_sentinel.domain.exceptions import (
    CausalOrderingError,
    DuplicateConflictError,
)
from card_testing_sentinel.persistence.sqlite_repository import SQLiteStateRepository
from card_testing_sentinel.security.identifiers import IdentifierProtector
from card_testing_sentinel.services.demo import DemoManager
from card_testing_sentinel.services.fraud_detection import FraudDetectionService
from card_testing_sentinel.services.scenario_generation import SCENARIO_PLANS

SECRET = "demo-orchestration-test-secret-0123456789"


def _registry_view(registry):
    """The subset of ArtifactRegistry a FraudDetectionService needs --
    mirrors the pattern already used in test_persistence_restart.py."""
    return SimpleNamespace(
        scorer=registry.scorer,
        policy=registry.policy,
        model_version=registry.model_version,
        policy_version=registry.policy_version,
    )


def _service(registry, path, secret=SECRET):
    return FraudDetectionService(
        _registry_view(registry),
        SQLiteStateRepository(path),
        IdentifierProtector.from_secret(secret),
    )


async def _run_scenario(demo, scenario):
    started = demo.start(scenario)
    demo_id = started["demo_id"]
    results = []
    while True:
        result = await demo.step(demo_id)
        if result["complete"] and "operations" not in result:
            break
        results.append(result)
        if result["complete"]:
            break
    return demo_id, results


# ---------------------------------------------------------------------------
# Real service, real repository -- no duplicate scoring path.
# ---------------------------------------------------------------------------


def test_demo_manager_is_handed_the_real_shared_service(client):
    """DemoManager must be the exact same FraudDetectionService instance
    live /api/precheck traffic uses -- not a lookalike, not a copy."""
    runtime = client.app.state.runtime
    assert runtime.demo.service is runtime.service


def test_demo_run_persists_through_the_same_sqlite_repository(registry, tmp_path):
    service = _service(registry, tmp_path / "demo.sqlite3")
    protector = service.protector
    demo = DemoManager(service, protector)
    before = service.repository.status()["requests"]

    demo_id, results = asyncio.run(_run_scenario(demo, "normal_customer"))

    after = service.repository.status()["requests"]
    assert after == before + len(SCENARIO_PLANS["normal_customer"])
    assert all(
        row["operations"]["decision"] in {"allow", "review", "block"} for row in results
    )
    service.close()


def test_reset_clears_only_the_cursor_never_the_audit_history(registry, tmp_path):
    service = _service(registry, tmp_path / "demo.sqlite3")
    demo = DemoManager(service, service.protector)
    demo_id, _ = asyncio.run(_run_scenario(demo, "normal_customer"))
    requests_before_reset = service.repository.status()["requests"]
    events_before_reset = service.repository.status()["events"]
    assert demo_id in demo.runs

    result = demo.reset()

    assert result == {"reset": True}
    assert demo.runs == {}
    assert service.repository.status()["requests"] == requests_before_reset
    assert service.repository.status()["events"] == events_before_reset
    service.close()


# ---------------------------------------------------------------------------
# Block suppresses outcome/checkout; later requests remain scoreable.
# ---------------------------------------------------------------------------


def test_block_suppresses_outcome_and_checkout_and_later_attempts_still_score(
    registry, tmp_path
):
    service = _service(registry, tmp_path / "demo.sqlite3")
    demo = DemoManager(service, service.protector)
    demo_id, results = asyncio.run(_run_scenario(demo, "burst_attacker"))

    blocked = [row for row in results if row["operations"]["decision"] == "block"]
    assert blocked, "burst_attacker is expected to trigger at least one block"
    for row in blocked:
        assert row["operations"]["authorization"] == "suppressed"
        assert row["operations"]["outcome_status"] is None
        assert row["operations"]["checkout_status"] is None

    # every attempt after the first block was still scored, not skipped --
    # proving a blocked device can still be scored on its next request.
    first_block_position = blocked[0]["position"]
    later = [row for row in results if row["position"] > first_block_position]
    assert later
    assert all(
        row["operations"]["decision"] in {"allow", "review", "block"} for row in later
    )

    events_count = service.repository.status()["events"]
    # events are only outcomes/checkouts; blocked attempts contribute none
    non_blocked_attempts = len(results) - len(blocked)
    assert events_count <= non_blocked_attempts * 2  # outcome (+ optional checkout)
    service.close()


# ---------------------------------------------------------------------------
# Idempotency, conflicts, lateness -- via the same precheck_with_evidence
# path the demo uses.
# ---------------------------------------------------------------------------


def _precheck_request(**overrides) -> PrecheckRequest:
    base = dict(
        request_id="orchestration-request-1",
        event_id="orchestration-precheck-1",
        device_id="orchestration-device",
        session_id="orchestration-session",
        card_reference="orchestration-card",
        card_bin="410000",
        ip_reference="orchestration-ip",
        amount=12.0,
        currency="USD",
        timestamp=datetime(2033, 1, 1, tzinfo=UTC),
        event_sequence=1,
        campaign_active=False,
    )
    base.update(overrides)
    return PrecheckRequest(**base)


def test_idempotent_retry_via_precheck_with_evidence_preserves_original_evidence(
    registry, tmp_path
):
    """An idempotent replay must never recompute a snapshot (that would be
    rescoring), but it also must not discard the original decision's
    evidence -- the fraud-operations panel should be able to show the
    operator exactly what was true when the decision was actually made,
    labeled as a replay, rather than an empty projection that reads as
    "nothing was ever observed"."""
    service = _service(registry, tmp_path / "demo.sqlite3")
    request = _precheck_request()
    first, first_evidence = asyncio.run(service.precheck_with_evidence(request))
    calls = service.model_score_calls
    assert first_evidence  # a fresh decision has evidence

    second, second_evidence = asyncio.run(service.precheck_with_evidence(request))

    assert second.idempotent_replay is True
    assert second.decision == first.decision
    assert second.device_state_version == first.device_state_version
    assert service.model_score_calls == calls  # no rescoring happened
    # The replay's evidence is the *original* decision's evidence, returned
    # verbatim from storage -- not recomputed (which would be indistinguishable
    # from rescoring) and not fabricated as empty.
    assert second_evidence == first_evidence
    service.close()


def test_conflicting_retry_via_precheck_with_evidence_raises_409_equivalent(
    registry, tmp_path
):
    service = _service(registry, tmp_path / "demo.sqlite3")
    request = _precheck_request()
    asyncio.run(service.precheck_with_evidence(request))

    with pytest.raises(DuplicateConflictError):
        asyncio.run(service.precheck_with_evidence(_precheck_request(amount=99.0)))
    service.close()


def test_late_event_via_precheck_with_evidence_is_rejected(registry, tmp_path):
    service = _service(registry, tmp_path / "demo.sqlite3")
    asyncio.run(
        service.precheck_with_evidence(
            _precheck_request(
                request_id="orchestration-request-2",
                event_id="orchestration-precheck-2",
                timestamp=datetime(2033, 1, 1, 0, 1, tzinfo=UTC),
                event_sequence=2,
            )
        )
    )

    with pytest.raises(CausalOrderingError):
        asyncio.run(
            service.precheck_with_evidence(
                _precheck_request(
                    request_id="orchestration-request-3",
                    event_id="orchestration-precheck-3",
                    timestamp=datetime(2033, 1, 1, 0, 0, tzinfo=UTC),
                    event_sequence=1,
                )
            )
        )
    service.close()


# ---------------------------------------------------------------------------
# Clock seeding: this is a direct regression test for the exact bug caught
# during Stage 3-4 development, where a scenario's later attempts used
# non-cumulative offsets and collided with the scenario's own earlier rows.
# ---------------------------------------------------------------------------


def test_clock_anchor_is_strictly_after_a_future_dated_persisted_row(
    registry, tmp_path
):
    service = _service(registry, tmp_path / "demo.sqlite3")
    demo = DemoManager(service, service.protector)

    far_future = datetime(2099, 1, 1, tzinfo=UTC)
    asyncio.run(
        service.precheck_with_evidence(
            _precheck_request(
                request_id="future-request",
                event_id="future-precheck",
                device_id="unrelated-future-device",
                timestamp=far_future,
                event_sequence=1,
            )
        )
    )

    anchor = demo._clock_anchor()
    assert anchor > far_future

    # and a fresh scenario run must not raise a late-event error because of
    # that pre-existing future-dated row.
    demo_id, results = asyncio.run(_run_scenario(demo, "normal_customer"))
    assert results
    service.close()


def test_scenario_runs_never_use_wall_clock_time_when_history_exists(
    registry, tmp_path
):
    """Every attempt timestamp inside one run must land strictly after the
    previous attempt within the same run -- proving gaps accumulate rather
    than each being a fresh offset from the anchor (the earlier bug)."""
    service = _service(registry, tmp_path / "demo.sqlite3")
    demo = DemoManager(service, service.protector)
    demo_id, _ = asyncio.run(_run_scenario(demo, "normal_bad_luck"))
    timeline = service.timeline(f"{demo_id}_device")
    timestamps = [row["timestamp"] for row in timeline]
    assert timestamps == sorted(timestamps)
    assert len(timestamps) == len(set(timestamps))  # strictly increasing, no ties
    service.close()


# ---------------------------------------------------------------------------
# Restart recovery.
# ---------------------------------------------------------------------------


def test_restart_recovers_demo_decisions_and_state_versions(registry, tmp_path):
    path = tmp_path / "demo_restart.sqlite3"
    first_service = _service(registry, path)
    demo = DemoManager(first_service, first_service.protector)
    demo_id, results = asyncio.run(_run_scenario(demo, "evasive_attacker"))
    first_status = first_service.repository.status()
    first_service.close()

    second_service = _service(registry, path)
    second_status = second_service.repository.status()
    assert second_status["requests"] == first_status["requests"]
    assert second_status["events"] == first_status["events"]
    assert second_status["integrity"] == "ok"
    assert second_service.model_score_calls == 0  # rebuild replays, never rescoring

    final_position_device = f"{demo_id}_device"
    recovered_timeline = second_service.timeline(final_position_device)
    assert len(recovered_timeline) == len(
        second_service.repository.device_timeline(
            second_service.protector.protect("device", final_position_device)
        )
    )
    second_service.close()


# ---------------------------------------------------------------------------
# No raw identifiers/secrets leak; blind data untouched; artifacts unchanged.
# ---------------------------------------------------------------------------


def test_no_raw_demo_identifiers_or_secret_in_sqlite_or_responses(registry, tmp_path):
    path = tmp_path / "demo.sqlite3"
    service = _service(registry, path)
    demo = DemoManager(service, service.protector)
    demo_id, results = asyncio.run(_run_scenario(demo, "patient_attacker"))
    service.close()

    raw_device_id = f"{demo_id}_device"
    connection = sqlite3.connect(path)
    database_text = " ".join(
        str(value)
        for table in ("requests", "lifecycle_events")
        for row in connection.execute(f"SELECT * FROM {table}").fetchall()
        for value in row
    )
    connection.close()

    assert raw_device_id not in database_text
    assert SECRET not in database_text
    for row in results:
        encoded = str(row)
        assert raw_device_id not in encoded
        assert SECRET not in encoded


def test_demo_scenarios_never_touch_blind_evaluation_rows(client):
    runtime = client.app.state.runtime
    registry = runtime.registry
    assert registry._blind_decisions is None
    assert registry._blind_devices is None
    blind_row_load_count_before = registry.blind_row_load_count
    calls_before = runtime.service.model_score_calls

    demo_id, results = asyncio.run(_run_scenario(runtime.demo, "flash_standard"))

    assert registry._blind_decisions is None
    assert registry._blind_devices is None
    assert registry.blind_row_load_count == blind_row_load_count_before == 0
    fresh_score_calls = sum(
        0 if row["operations"]["idempotent_replay"] else 1 for row in results
    )
    assert runtime.service.model_score_calls == calls_before + fresh_score_calls


def test_protected_artifact_hashes_are_unchanged_after_demo_runs(registry, tmp_path):
    root = registry.root
    manifest_before = verify_manifest(root, root / "artifacts/release_manifest.json")

    service = _service(registry, tmp_path / "demo.sqlite3")
    demo = DemoManager(service, service.protector)
    asyncio.run(_run_scenario(demo, "burst_attacker"))
    service.close()

    manifest_after = verify_manifest(root, root / "artifacts/release_manifest.json")
    assert manifest_after == manifest_before
    for name, entry in manifest_before["artifacts"].items():
        assert sha256_file(root / entry["path"]) == entry["sha256"], name
