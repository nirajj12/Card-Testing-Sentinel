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
