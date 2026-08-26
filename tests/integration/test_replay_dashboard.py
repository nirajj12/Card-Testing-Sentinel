import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]


def _install_saved_replay_fixture(client):
    """Exercise replay projections without opening protected blind-row CSVs."""
    registry = client.app.state.runtime.registry
    registry._blind_devices = pd.DataFrame(
        [
            {
                "device_id": "saved_burst_device",
                "population": "attack",
                "attack_subtype": "burst",
                "review_or_higher": True,
                "blocked": True,
                "first_review_or_higher_request": 4,
                "first_block_request": 4,
            },
            {
                "device_id": "saved_patient_device",
                "population": "attack",
                "attack_subtype": "patient",
                "review_or_higher": False,
                "blocked": False,
                "first_review_or_higher_request": None,
                "first_block_request": None,
            },
        ]
    )
    registry._blind_decisions = pd.DataFrame(
        [
            {
                "device_id": "saved_burst_device",
                "request_index": 4,
                "action": "block",
                "calibrated_probability": 0.9,
                "rule_score": 3,
            }
        ]
    )
    assert registry.blind_row_load_count == 0
    return registry


def test_replay_endpoints_return_saved_rows_without_model_scoring(client):
    registry = _install_saved_replay_fixture(client)
    service = client.app.state.runtime.service
    calls = service.model_score_calls
    metrics = client.get("/api/metrics/blind")
    assert metrics.status_code == 200
    assert metrics.json()["status"] == "blind_completed_passed"
    devices = client.get(
        "/api/replay/devices",
        params={"population": "attack", "attack_subtype": "burst", "limit": 2},
    )
    assert devices.status_code == 200
    assert devices.json()["rescored"] is False
    device_id = devices.json()["items"][0]["device_id"]
    timeline = client.get(f"/api/replay/devices/{device_id}/timeline")
    assert timeline.status_code == 200
    assert timeline.json()["rescored"] is False
    assert service.model_score_calls == calls
    assert registry.blind_row_load_count == 0


def test_frozen_metrics_are_the_loaded_artifact_values(client):
    response = client.get("/api/metrics/blind")
    registry = client.app.state.runtime.registry
    assert (
        response.json()["operational_policy"]
        == registry.blind_metrics["operational_policy"]
    )
    assert response.json()["action_counts"] == registry.blind_metrics["action_counts"]


def test_replay_filters_and_empty_state(client):
    registry = _install_saved_replay_fixture(client)
    never = client.get(
        "/api/replay/devices",
        params={"attack_subtype": "patient", "detected": "false", "limit": 200},
    ).json()
    assert never["count"] == 1
    empty = client.get(
        "/api/replay/devices",
        params={"population": "normal", "attack_subtype": "burst"},
    ).json()
    assert empty["count"] == 0
    assert registry.blind_row_load_count == 0


def test_system_response_is_safe_and_complete(client):
    body = client.get("/api/system").json()
    assert body["ready"] is True
    assert body["feature_count"] == 44
    assert body["artifact_load_count"] == 1
    encoded = str(body)
    assert "CTS_HMAC_SECRET" not in encoded
    assert "/Users/" not in encoded


def test_precheck_response_and_html_do_not_echo_sensitive_values(client):
    from tests.helpers import precheck_payload

    payload = precheck_payload(card="sensitive-card-token", ip="203.0.113.77")
    response = client.post("/api/precheck", json=payload)
    encoded = response.text
    assert response.status_code == 200
    assert payload["card_reference"] not in encoded
    assert payload["ip_reference"] not in encoded
    assert payload["card_reference"] not in client.get("/").text
    assert payload["ip_reference"] not in client.get("/").text


def test_demo_uses_the_real_shared_sqlite_backed_service(client):
    """Stage 4: the demo drives the *same* FraudDetectionService and SQLite
    repository as live traffic -- a demo step is a real, persisted request,
    not a separate in-memory implementation -- and `reset` only clears the
    demo's own cursor, never the shared audit history it just wrote."""
    runtime_service = client.app.state.runtime.service
    before = runtime_service.repository.status()["requests"]
    scenario = client.get("/api/demo/scenarios").json()["items"][4]
    started = client.post("/api/demo/start", json={"scenario": scenario["id"]})
    assert started.status_code == 200
    step = client.post("/api/demo/step", json={"demo_id": started.json()["demo_id"]})
    assert step.status_code == 200
    body = step.json()
    assert "operations" in body
    assert body["operations"]["decision"] in {"allow", "review", "block"}
    assert "risk_score" in body["operations"]
    assert runtime_service.repository.status()["requests"] == before + 1
    assert client.post("/api/demo/reset", json={}).json()["reset"] is True
    assert runtime_service.repository.status()["requests"] == before + 1


def test_product_page_has_no_framework_cdn_or_inline_javascript(client):
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
    ):
        assert forbidden not in html
    # Exactly one script tag, module type, served same-origin, never inline.
    assert html.count("<script") == 1
    assert '<script type="module" src="/static/dashboard.js' in html
    # External navigation is restricted to the project's own GitHub evidence.
    external_links = re.findall(r'href="(https://[^"]+)"', html)
    assert external_links
    assert all(
        link.startswith("https://github.com/nirajj12/card-testing-sentinel")
        for link in external_links
    )
    # The old research-dashboard hierarchy is gone from the product page.
    for removed in (
        "Frozen Evaluation",
        "Blind Replay",
        "System Integrity",
        "Advanced API Proof",
    ):
        assert removed.lower() not in html
    for required in (
        "Live Merchant Protection",
        "Customer view",
        "Fraud Operations",
        "Authoritative Transaction Timeline",
        "How a request is decided",
    ):
        assert required.lower() in html
    assert 'id="verified-results-grid"' in html
    assert 'id="customer-status"' in html
    assert 'id="ops-body"' in html


def test_mandatory_limitations_are_served_from_the_frozen_artifact(client):
    """The disclosure list must come from the artifact, not hardcoded markup."""
    payload = client.get("/api/metrics/blind").json()
    limitations = payload["limitations"]
    assert len(limitations) == 10
    joined = " ".join(limitations).lower()
    assert "risk score is not a guaranteed fraud probability" in joined
    assert "no attacker was detected within the first three attempts" in joined
    assert "29 of 300 blind attackers were never detected" in joined
    assert "offline replay upper bound" in joined
    assert "synthetic data" in joined
    # Detection-latency numbers are derived, never typed by hand.
    latency = payload["detection_latency"]
    assert latency["median_first_review_attempt"] == 5
    assert latency["median_first_block_attempt"] == 7
    assert f"attempt {latency['median_first_review_attempt']}." in joined
    assert f"attempt {latency['median_first_block_attempt']}." in joined
    # Denominators are served so the dashboard never hardcodes 1,700 / 300.
    assert payload["denominators"]["legitimate_devices"] == 1700
    assert payload["denominators"]["attacker_devices"] == 300


def test_frontend_modules_use_safe_dom_and_responsive_css():
    static = ROOT / "src/card_testing_sentinel/web/static"
    scripts = "\n".join(path.read_text() for path in static.glob("*.js"))
    # No raw-markup assignment and no dynamic evaluation anywhere.
    assert "innerHTML" not in scripts
    assert "insertAdjacentHTML" not in scripts
    assert "eval(" not in scripts
    assert "textContent" in scripts
    # Attempt numbering still falls back to positional order for live rows.
    assert "row.request_index || index + 1" in scripts
    assert "Loading verified evidence and runtime state" in scripts
    css = (static / "dashboard.css").read_text()
    assert "@media (max-width: 560px)" in css
    assert "overflow-x: hidden" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert ":focus-visible" in css


def test_customer_checkout_markup_contains_no_internal_risk_fields(client):
    html = client.get("/").text
    customer = html.split('class="product-panel checkout-panel"', 1)[1].split(
        'class="product-panel operations-panel"', 1
    )[0]
    for forbidden in (
        "risk score",
        "risk band",
        "rule score",
        "reason code",
        "device identifier",
        "session identifier",
        "ip information",
        "state version",
        "scenario name",
    ):
        assert forbidden not in customer.lower()
    assert "No PAN, CVV or expiry is collected" in customer


def test_console_uses_the_real_production_endpoints():
    """The dashboard must exercise the live path, not only the demo path."""
    static = ROOT / "src/card_testing_sentinel/web/static"
    client_source = (static / "api-client.js").read_text()
    for route in (
        "/api/precheck",
        "/api/outcomes",
        "/api/checkouts",
        "/api/runtime/decisions",
    ):
        assert route in client_source
    console = (static / "console-controller.js").read_text()
    assert "api.precheck" in console
    assert "sendIdempotentRetry" in console
    assert "409" in console
