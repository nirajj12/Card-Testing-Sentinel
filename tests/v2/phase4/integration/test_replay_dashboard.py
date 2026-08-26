from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def test_blind_endpoints_read_saved_rows_without_model_scoring(client):
    service = client.app.state.phase4.service
    calls = service.model_score_calls
    metrics = client.get("/api/v2/metrics/blind")
    assert metrics.status_code == 200
    assert metrics.json()["status"] == "blind_completed_passed"
    devices = client.get(
        "/api/v2/replay/devices",
        params={"population": "attack", "attack_subtype": "burst", "limit": 2},
    )
    assert devices.status_code == 200
    assert devices.json()["rescored"] is False
    device_id = devices.json()["items"][0]["device_id"]
    timeline = client.get(f"/api/v2/replay/devices/{device_id}/timeline")
    assert timeline.status_code == 200
    assert timeline.json()["rescored"] is False
    assert service.model_score_calls == calls


def test_frozen_metrics_are_the_loaded_artifact_values(client):
    response = client.get("/api/v2/metrics/blind")
    registry = client.app.state.phase4.registry
    assert (
        response.json()["operational_policy"]
        == registry.blind_metrics["operational_policy"]
    )
    assert response.json()["action_counts"] == registry.blind_metrics["action_counts"]


def test_replay_filters_and_empty_state(client):
    never = client.get(
        "/api/v2/replay/devices",
        params={"attack_subtype": "patient", "detected": "false", "limit": 200},
    ).json()
    assert never["count"] == 18
    empty = client.get(
        "/api/v2/replay/devices",
        params={"population": "normal", "attack_subtype": "burst"},
    ).json()
    assert empty["count"] == 0


def test_system_response_is_safe_and_complete(client):
    body = client.get("/api/v2/system").json()
    assert body["ready"] is True
    assert body["feature_count"] == 44
    assert body["artifact_load_count"] == 1
    encoded = str(body)
    assert "CTS_HMAC_SECRET" not in encoded
    assert "/Users/" not in encoded


def test_precheck_response_and_html_do_not_echo_sensitive_values(client):
    from tests.v2.phase4.helpers import precheck_payload

    payload = precheck_payload(card="sensitive-card-token", ip="203.0.113.77")
    response = client.post("/api/v2/precheck", json=payload)
    encoded = response.text
    assert response.status_code == 200
    assert payload["card_reference"] not in encoded
    assert payload["ip_reference"] not in encoded
    assert payload["card_reference"] not in client.get("/").text
    assert payload["ip_reference"] not in client.get("/").text


def test_demo_state_is_separate_from_runtime(client):
    runtime_service = client.app.state.phase4.service
    before = runtime_service.repository.status()["requests"]
    scenario = client.get("/api/v2/demo/scenarios").json()["items"][4]
    started = client.post("/api/v2/demo/start", json={"scenario": scenario["id"]})
    assert started.status_code == 200
    step = client.post("/api/v2/demo/step", json={"demo_id": started.json()["demo_id"]})
    assert step.status_code == 200
    assert "risk_score" in step.json()["decision"]
    assert runtime_service.repository.status()["requests"] == before
    assert client.post("/api/v2/demo/reset", json={}).json()["reset"] is True


def test_dashboard_has_no_framework_cdn_or_inline_javascript(client):
    response = client.get("/")
    assert response.status_code == 200
    html = response.text.lower()
    for forbidden in (
        "react",
        "vue",
        "angular",
        "jquery",
        "bootstrap",
        "tailwind",
        "chart.js",
        "cdn.",
        "http://",
        "https://",
    ):
        assert forbidden not in html
    expected_script = (
        '<script type="module" '
        'src="/static/v2/phase4/dashboard.js?v=phase4-2"></script>'
    )
    assert expected_script in html
    assert "risk score is not a guaranteed fraud probability" in html
    assert "detected no attackers within the first three attempts" in html
    assert "twenty-nine of 300 blind attackers were never detected" in html
    assert "offline replay upper bound" in html
    warning_list = html.split('<ul id="mandatory-warnings"', 1)[1].split("</ul>", 1)[0]
    assert warning_list.count("<li>") == 10


def test_frontend_modules_use_safe_dom_and_responsive_css():
    static = ROOT / "src/card_testing_sentinel/v2/phase4/static"
    scripts = "\n".join(path.read_text() for path in static.glob("*.js"))
    assert "innerHTML" not in scripts
    assert "eval(" not in scripts
    assert "textContent" in scripts
    assert "item.request_index || authorizationAttempt" in scripts
    assert "Loading verified evidence and runtime state" in scripts
    css = (static / "dashboard.css").read_text()
    assert "@media (max-width: 480px)" in css
    assert "overflow-x: hidden" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert ":focus-visible" in css
