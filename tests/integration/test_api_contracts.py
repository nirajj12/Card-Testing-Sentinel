from card_testing_sentinel.api.contracts import PrecheckRequest
from card_testing_sentinel.domain.events import LifecycleEvent
from tests.helpers import outcome_payload, precheck_payload


def test_valid_precheck_safe_schema(client):
    response = client.post("/api/precheck", json=precheck_payload())
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] in {"allow", "review", "block"}
    assert body["device_state_version"] == 1
    assert body["idempotent_replay"] is False
    assert "risk_score" in body
    forbidden = {
        "features",
        "card_reference",
        "card_bin",
        "ip_reference",
        "raw_probability",
        "threshold",
    }
    assert forbidden.isdisjoint(body)
    assert body["model_status"] == "ready"
    assert body["decision_basis"] == "model_and_rules"
    assert 0.0 <= body["risk_score"] <= 1.0


def test_missing_extra_sensitive_and_client_feature_fields_rejected(client):
    base = precheck_payload()
    cases = [
        {key: value for key, value in base.items() if key != "amount"},
        {**base, "population": "attack"},
        {**base, "scenario_tag": "attack_burst"},
        {**base, "label": 1},
        {**base, "prior_attempts_5m": 10},
        {**base, "risk_score": 0.9},
        {**base, "threshold": 0.4},
        {**base, "pan": "4111111111111111"},
        {**base, "cvv": "123"},
        {**base, "expiry": "12/30"},
        {**base, "authorization_result": "declined"},
        {**base, "card_reference": "tok-1"},
        {**base, "card_bin": "410000"},
        {**base, "payment_method": "card"},
    ]
    for payload in cases:
        assert client.post("/api/precheck", json=payload).status_code == 422


def test_boolean_and_nonfinite_numeric_rejected(client):
    assert (
        client.post(
            "/api/precheck", json={**precheck_payload(), "amount": True}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/precheck",
            content=__import__("json").dumps(
                {**precheck_payload(), "amount": float("inf")}
            ),
            headers={"Content-Type": "application/json"},
        ).status_code
        == 422
    )


def test_precheck_idempotent_and_conflicting_retry(client):
    payload = precheck_payload()
    first = client.post("/api/precheck", json=payload).json()
    service = client.app.state.runtime.service
    calls = service.model_score_calls
    retry = client.post("/api/precheck", json=payload)
    assert retry.status_code == 200
    assert retry.json()["decision"] == first["decision"]
    assert retry.json()["device_state_version"] == first["device_state_version"]
    assert retry.json()["idempotent_replay"] is True
    assert service.model_score_calls == calls
    conflict = client.post(
        "/api/precheck", json={**payload, "amount": payload["amount"] + 1}
    )
    assert conflict.status_code == 409


def test_public_lifecycle_injection_routes_are_absent_and_change_no_risk_state(client):
    first = precheck_payload()
    assert client.post("/api/precheck", json=first).status_code == 200

    service = client.app.state.runtime.service
    next_request = PrecheckRequest.model_validate(precheck_payload(2))
    next_event = LifecycleEvent.model_validate(service._request_payload(next_request))
    snapshot_before = service.engine.snapshot(next_event)
    score_before = service.registry.model.score(snapshot_before)
    events_before = list(service.repository.events_in_order())

    outcome = client.post("/api/outcomes", json=outcome_payload(with_card=True))
    checkout = client.post(
        "/api/checkouts",
        json={
            "event_id": "checkout-1",
            "request_id": "request-1",
            "device_id": "device-demo",
            "session_id": "session-demo",
            "timestamp": "2030-01-01T00:00:12+00:00",
            "event_sequence": 5,
        },
    )

    assert outcome.status_code == 404
    assert checkout.status_code == 404
    assert service.repository.events_in_order() == events_before
    snapshot_after = service.engine.snapshot(next_event)
    assert snapshot_after == snapshot_before
    assert service.registry.model.score(snapshot_after) == score_before


def test_late_event_rejected(client, base_time):
    assert (
        client.post(
            "/api/precheck", json=precheck_payload(2, base=base_time)
        ).status_code
        == 200
    )
    late = client.post("/api/precheck", json=precheck_payload(1, base=base_time))
    assert late.status_code == 409
    assert late.json()["error"] == "causal_ordering_error"
