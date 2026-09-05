"""The demo orchestrator drives the same shared RiskService + SQLite
repository that live /api/precheck traffic uses -- no second scoring path,
no second repository -- and `reset` never erases persisted audit history.
"""

from __future__ import annotations

import asyncio

from card_testing_sentinel.persistence.sqlite_repository import SQLiteStateRepository
from card_testing_sentinel.security.identifiers import IdentifierProtector
from card_testing_sentinel.services.demo import DemoManager
from card_testing_sentinel.services.risk_service import RiskService
from card_testing_sentinel.services.scenario_generation import SCENARIO_PLANS

SECRET = "demo-orchestration-secret-0123456789"


def _service(registry, path):
    return RiskService(
        registry, SQLiteStateRepository(path), IdentifierProtector.from_secret(SECRET)
    )


async def _run_scenario(demo, scenario):
    started = demo.start(scenario)
    results = []
    while True:
        result = await demo.step(started["demo_id"])
        if "operations" in result:
            results.append(result)
        if result["complete"]:
            break
    return started["demo_id"], results


def test_demo_manager_uses_the_exact_shared_service(client):
    runtime = client.app.state.runtime
    assert runtime.demo.service is runtime.service


def test_demo_run_persists_through_the_same_repository(registry, tmp_path):
    service = _service(registry, tmp_path / "demo.sqlite3")
    demo = DemoManager(service, service.protector)
    before = service.repository.status()["requests"]

    _, results = asyncio.run(_run_scenario(demo, "normal_customer"))

    assert service.repository.status()["requests"] == before + len(
        SCENARIO_PLANS["normal_customer"]
    )
    assert all(
        row["operations"]["decision"] in {"allow", "review", "block"} for row in results
    )
    assert all(0.0 <= row["operations"]["risk_score"] <= 1.0 for row in results)
    service.close()


def test_reset_clears_the_cursor_only_never_the_audit_history(registry, tmp_path):
    service = _service(registry, tmp_path / "demo.sqlite3")
    demo = DemoManager(service, service.protector)
    demo_id, _ = asyncio.run(_run_scenario(demo, "burst_attacker"))
    requests_before = service.repository.status()["requests"]
    events_before = service.repository.status()["events"]
    assert demo_id in demo.runs

    assert demo.reset() == {"reset": True}
    assert demo.runs == {}
    assert service.repository.status()["requests"] == requests_before
    assert service.repository.status()["events"] == events_before
    service.close()


def test_burst_attacker_reaches_review_or_block_in_rules_only_mode(registry, tmp_path):
    service = _service(registry, tmp_path / "demo.sqlite3")
    demo = DemoManager(service, service.protector)
    _, results = asyncio.run(_run_scenario(demo, "burst_attacker"))
    actions = {row["operations"]["decision"] for row in results}
    assert actions & {"review", "block"}


def test_restart_recovers_demo_decisions(registry, tmp_path):
    path = tmp_path / "demo.sqlite3"
    first = _service(registry, path)
    demo = DemoManager(first, first.protector)
    _, results = asyncio.run(_run_scenario(demo, "evasive_attacker"))
    decisions = [row["operations"]["decision"] for row in results]
    first.close()

    second = _service(registry, path)
    recovered = [row["decision"] for row in second.decisions(len(decisions))][::-1]
    assert recovered == decisions
    second.close()


def test_demo_lifecycle_semantics_by_decision(registry, tmp_path):
    """ALLOW attempts schedule synthetic outcome/checkout events; REVIEW and
    BLOCK suppress authorization and schedule zero outcomes."""
    service = _service(registry, tmp_path / "demo.sqlite3")
    demo = DemoManager(service, service.protector)
    _, results = asyncio.run(_run_scenario(demo, "burst_attacker"))

    allow_results = [r for r in results if r["operations"]["decision"] == "allow"]
    review_results = [r for r in results if r["operations"]["decision"] == "review"]
    block_results = [r for r in results if r["operations"]["decision"] == "block"]

    assert len(allow_results) > 0
    assert len(review_results) > 0
    assert len(block_results) > 0

    for res in allow_results:
        ops = res["operations"]
        assert ops["authorization"] == "sent"
        assert ops["outcome_status"] in {"approved", "declined"}

    for res in review_results:
        ops = res["operations"]
        assert ops["authorization"] == "suppressed"
        assert ops["outcome_status"] is None
        assert ops["checkout_status"] is None

    for res in block_results:
        ops = res["operations"]
        assert ops["authorization"] == "suppressed"
        assert ops["outcome_status"] is None
        assert ops["checkout_status"] is None

    service.close()


def test_demo_review_attempt_produces_no_outcome_event_or_card_history(
    registry, tmp_path
):
    """When an attempt is REVIEW, no synthetic outcome is recorded in repository,
    so subsequent attempts inherit zero card/decline history from that attempt."""
    service = _service(registry, tmp_path / "demo.sqlite3")
    demo = DemoManager(service, service.protector)

    started = demo.start("burst_attacker")
    demo_id = started["demo_id"]

    events_before = service.repository.status()["events"]
    assert events_before == 0

    # Step 1 evaluates to REVIEW
    res1 = asyncio.run(demo.step(demo_id))
    assert res1["operations"]["decision"] == "review"
    assert res1["operations"]["authorization"] == "suppressed"
    assert res1["operations"]["outcome_status"] is None
    # No outcome event created for reviewed attempt
    assert service.repository.status()["events"] == 0

    # Step 2 evaluates to ALLOW
    res2 = asyncio.run(demo.step(demo_id))
    assert res2["operations"]["decision"] == "allow"
    assert res2["operations"]["authorization"] == "sent"
    # Exactly one outcome event created now (from Step 2)
    assert service.repository.status()["events"] == 1

    service.close()
