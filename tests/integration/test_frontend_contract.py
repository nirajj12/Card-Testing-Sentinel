"""Closes the "frontend contract" verification gap: proves, with real
assertions rather than a claim, that the JavaScript API surface matches the
live FastAPI route table and the real Pydantic request/response contracts,
and exercises the demo/blind-evaluation lifecycle end-to-end through the
real app factory (never a second, hand-rolled scoring path).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
API_CLIENT_JS = ROOT / "src/card_testing_sentinel/web/static/api-client.js"
DASHBOARD_JS = ROOT / "src/card_testing_sentinel/web/static/dashboard.js"
CONSOLE_JS = ROOT / "src/card_testing_sentinel/web/static/console-controller.js"

_STRING_PATH = re.compile(r'"(/(?:health|api)[^"?]*)"')
_TEMPLATE_PATH = re.compile(r"`(/(?:health|api)[^`?]*)`")


def _extract_js_paths(source: str) -> set[str]:
    """Every literal or template-literal path the frontend ever calls,
    normalized so a `${...}` interpolation becomes a `{param}` placeholder
    -- the same shape FastAPI's own route.path uses."""
    paths = set()
    for match in _STRING_PATH.finditer(source):
        paths.add(match.group(1))
    for match in _TEMPLATE_PATH.finditer(source):
        normalized = re.sub(r"\$\{[^}]*\}", "{param}", match.group(1))
        paths.add(normalized)
    return paths


def _route_matches(js_path: str, route_path: str) -> bool:
    """True if a JS path (with `{param}` placeholders for interpolated
    segments) could resolve to this FastAPI route path (with its own
    `{name}` placeholders)."""
    js_segments = js_path.strip("/").split("/")
    route_segments = route_path.strip("/").split("/")
    if len(js_segments) != len(route_segments):
        return False
    for js_seg, route_seg in zip(js_segments, route_segments, strict=False):
        route_is_param = route_seg.startswith("{") and route_seg.endswith("}")
        js_is_param = js_seg == "{param}"
        if route_is_param:
            if not js_is_param:
                return False
        elif js_seg != route_seg:
            return False
    return True


def test_every_frontend_api_path_maps_to_a_registered_fastapi_route():
    """Every `/health/...` or `/api/...` path referenced anywhere in the
    frontend JS must resolve to a route the real FastAPI app actually
    registers -- a typo'd or stale endpoint fails this test instead of
    surfacing only as a runtime 404 a person happens to click into."""
    from card_testing_sentinel.app import create_app
    from card_testing_sentinel.persistence.memory_repository import (
        InMemoryStateRepository,
    )

    app = create_app(
        repository=InMemoryStateRepository(),
        hmac_secret="application-test-secret-at-least-sixteen-characters",
    )

    def registered_paths(routes):
        paths = set()
        for route in routes:
            path = getattr(route, "path", None)
            if path:
                paths.add(path)
            nested = getattr(route, "routes", None)
            if nested is None:
                nested = getattr(
                    getattr(route, "original_router", None), "routes", None
                )
            if nested:
                paths.update(registered_paths(nested))
        return paths

    registered = registered_paths(app.routes)

    js_paths: set[str] = set()
    js_paths |= _extract_js_paths(API_CLIENT_JS.read_text())
    # dashboard.js and console-controller.js must never bypass api-client.js
    # with their own raw fetch() calls to a path that isn't wrapped there.
    for extra in (DASHBOARD_JS, CONSOLE_JS):
        assert "fetch(" not in extra.read_text(), (
            f"{extra.name} must route every HTTP call through api-client.js, "
            "not call fetch() directly"
        )

    assert js_paths, "expected to find at least one API path in api-client.js"

    unmatched = [
        js_path
        for js_path in js_paths
        if not any(_route_matches(js_path, route_path) for route_path in registered)
    ]
    assert not unmatched, f"frontend paths with no matching FastAPI route: {unmatched}"


@pytest.mark.parametrize(
    "scenario",
    [
        "normal_customer",
        "normal_bad_luck",
        "flash_standard",
        "flash_hard_retry",
        "burst_attacker",
        "evasive_attacker",
        "patient_attacker",
    ],
)
def test_valid_scenario_start_returns_200_and_matches_the_start_contract(
    client, scenario
):
    response = client.post("/api/demo/start", json={"scenario": scenario})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"demo_id", "scenario", "total_attempts", "position"}
    assert body["scenario"] == scenario
    assert body["position"] == 0
    assert isinstance(body["total_attempts"], int) and body["total_attempts"] > 0


def test_invalid_scenario_returns_intentional_422(client):
    response = client.post("/api/demo/start", json={"scenario": "not_a_real_scenario"})
    assert response.status_code == 422


def test_valid_next_step_returns_200_and_updates_checkout_ops_and_timeline(
    client,
):
    demo_id = client.post(
        "/api/demo/start", json={"scenario": "normal_customer"}
    ).json()["demo_id"]

    response = client.post("/api/demo/step", json={"demo_id": demo_id})
    assert response.status_code == 200
    body = response.json()

    # The one real response is what drives checkout, operations, and the
    # timeline together -- there is no separate call for each panel, so
    # there is no way for them to disagree with each other.
    assert set(body) >= {
        "demo_id",
        "scenario",
        "complete",
        "position",
        "attempt",
        "operations",
        "timeline",
    }
    assert body["attempt"]["attempt"] == 1
    assert body["attempt"]["currency"] == "INR"
    # The backend holds an HMAC card fingerprint, never a PAN, so there is no
    # real last-four to display. The alias states what is actually known --
    # which distinct card this device is on -- instead of fabricating digits.
    assert body["attempt"]["timestamp"]
    assert body["attempt"]["elapsed_seconds"] == 0
    op = body["operations"]
    assert op["decision"] in {"allow", "review", "block"}
    assert set(op) == {
        "decision",
        "risk_score",
        "risk_band",
        "risk_score_label",
        "rule_score",
        "reason_codes",
        "state_version",
        "latency_ms",
        "idempotent_replay",
        "authorization",
        "outcome_status",
        "checkout_status",
        "evidence",
        "protected_reference",
    }
    assert 0.0 <= op["risk_score"] <= 1.0
    # evidence is either empty (idempotent replay with nothing stored) or
    # exactly the six-key allowlist -- never the 44-feature vector.
    allowed_evidence_keys = {
        "requests_5m",
        "recent_failures_24h",
        "decline_streak",
        "sessions_24h",
        "ip_changes_24h",
        "successful_checkouts",
    }
    assert set(op["evidence"]).issubset(allowed_evidence_keys)
    assert isinstance(body["timeline"], list) and body["timeline"]


def test_reset_returns_200(client):
    client.post("/api/demo/start", json={"scenario": "normal_customer"})
    response = client.post("/api/demo/reset", json={})
    assert response.status_code == 200
    assert response.json() == {"reset": True}


def test_blocked_attempt_response_displays_authorization_suppression_and_no_outcome(
    client,
):
    demo_id = client.post(
        "/api/demo/start", json={"scenario": "burst_attacker"}
    ).json()["demo_id"]
    blocked = None
    for _ in range(8):
        step = client.post("/api/demo/step", json={"demo_id": demo_id}).json()
        if step.get("operations", {}).get("decision") == "block":
            blocked = step["operations"]
            break
    assert blocked is not None, "burst_attacker is expected to trigger a block"
    assert blocked["authorization"] == "suppressed"
    assert blocked["outcome_status"] is None
    assert blocked["checkout_status"] is None


def test_idempotent_replay_via_raw_precheck_does_not_duplicate_timeline_rows(client):
    body = {
        "request_id": "contract-replay-request",
        "event_id": "contract-replay-precheck",
        "merchant_id": "contract-replay-merchant",
        "device_id": "contract-replay-device",
        "session_id": "contract-replay-session",
        "ip_reference": "198.51.100.200",
        "amount": 9.0,
        "currency": "USD",
        "timestamp": "2034-01-01T00:00:00+00:00",
        "event_sequence": 1,
        "campaign_active": False,
    }
    first = client.post("/api/precheck", json=body)
    assert first.status_code == 200
    assert first.json()["idempotent_replay"] is False

    second = client.post("/api/precheck", json=body)
    assert second.status_code == 200
    assert second.json()["idempotent_replay"] is True
    assert second.json()["request_id"] == first.json()["request_id"]

    timeline = client.get(f"/api/runtime/devices/{body['device_id']}/timeline").json()[
        "items"
    ]
    request_rows = [
        row for row in timeline if row.get("request_id") == body["request_id"]
    ]
    assert len(request_rows) == 1, "a replay must never create a second timeline row"


def test_frozen_evaluation_endpoint_never_triggers_model_scoring(client):
    runtime = client.app.state.runtime
    calls_before = runtime.service.model_score_calls
    response = client.get("/api/metrics/blind")
    assert response.status_code == 200
    assert (
        runtime.service.model_score_calls == calls_before
    ), "opening the frozen evaluation metrics must never call the scorer"


def test_system_reports_the_development_model_stage(client):
    body = client.get("/api/system").json()
    assert body["ready"] is True
    assert body["model_status"] == "ready"
    assert body["policy_mode"] == "model_and_rules"
    assert body["model_stage"] == "development_frozen_candidate"
    # no blind evaluation has run, and the runtime must say so
    assert body["evaluation_status"] == "development_validation_only"
    assert "no blind evaluation" in body["evaluation_reason"].lower()
    assert "journal_mode" in body["database"]
