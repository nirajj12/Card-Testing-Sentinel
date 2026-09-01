"""Product-page and runtime-safety checks that still hold in the
rules_only phase. The frozen-evaluation / blind-replay assertions were
removed with those artifacts; they return once Dataset V2 exists.
"""

import re
from pathlib import Path

from tests.helpers import precheck_payload

ROOT = Path(__file__).resolve().parents[2]


def test_evaluation_uses_the_frozen_artifact_and_replay_reports_its_state(client):
    metrics = client.get("/api/metrics/blind").json()
    assert metrics["status"] == "available"
    assert metrics["source"] == "artifacts/evaluation/blind_metrics_v1_1.json"
    assert "Synthetic" in metrics["disclosure"]

    replay = client.get("/api/replay/devices").json()
    assert replay["status"] == "unavailable"
    assert "Dataset V2" in replay["reason"]


def test_system_response_is_safe_and_reports_the_model_stage(client):
    body = client.get("/api/system").json()
    assert body["ready"] is True
    assert body["model_status"] == "ready"
    assert body["policy_mode"] == "model_and_rules"
    assert body["feature_count"] == body["feature_count"] and body["feature_count"] > 0
    encoded = str(body)
    assert "CTS_HMAC_SECRET" not in encoded
    assert "/Users/" not in encoded


def test_precheck_response_and_html_do_not_echo_sensitive_values(client):
    payload = precheck_payload(ip="203.0.113.77", merchant="secret-merchant-xyz")
    response = client.post("/api/precheck", json=payload)
    assert response.status_code == 200
    for raw in (payload["ip_reference"], payload["merchant_id"], payload["device_id"]):
        assert raw not in response.text
        assert raw not in client.get("/").text


def test_product_page_uses_the_built_spa_without_inline_javascript(client):
    html = client.get("/").text.lower()
    for forbidden in ("vue", "angular", "jquery", "bootstrap", "cdn."):
        assert forbidden not in html
    assert html.count("<script") == 1
    assert '<script type="module" crossorigin src="/assets/' in html
    # Standard Checkout is loaded only after a real ALLOW response; it is not
    # eagerly embedded into every route.
    assert "checkout.razorpay.com" not in html
    assert not re.search(r"<script[^>]*>\s*[^<\s]", html)


def test_frontend_modules_use_safe_dom_and_responsive_css():
    frontend = ROOT / "frontend/src"
    scripts = "\n".join(
        path.read_text()
        for path in frontend.rglob("*")
        if path.suffix in {".ts", ".tsx"}
    )
    assert "dangerouslySetInnerHTML" not in scripts
    assert "insertAdjacentHTML" not in scripts
    assert "eval(" not in scripts
    css = (frontend / "styles.css").read_text()
    assert "@media(max-width:640px)" in css
    assert "overflow-x:hidden" in css
    assert "@media(prefers-reduced-motion:reduce)" in css
    assert ":focus-visible" in css


def test_customer_checkout_markup_contains_no_internal_risk_fields(client):
    source = (ROOT / "frontend/src/pages/CheckoutPage.tsx").read_text()
    customer = source.split('<article className="checkout-form-card">', 1)[1].split(
        "<SentinelPanel", 1
    )[0]
    for forbidden in (
        "risk score",
        "risk band",
        "rule score",
        "reason code",
        "device identifier",
        "session identifier",
        "state version",
        "scenario name",
    ):
        assert forbidden not in customer.lower()
