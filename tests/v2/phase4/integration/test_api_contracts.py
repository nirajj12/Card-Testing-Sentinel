from tests.v2.phase4.helpers import outcome_payload, precheck_payload


def test_valid_precheck_safe_schema(client):
    response = client.post("/api/v2/precheck", json=precheck_payload())
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] in {"allow", "review", "block"}
    assert body["device_state_version"] == 1
    assert body["idempotent_replay"] is False
    assert "risk_score" in body
    forbidden = {
        "features",
        "card_reference",
        "ip_reference",
        "raw_probability",
        "threshold",
    }
    assert forbidden.isdisjoint(body)


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
    ]
    for payload in cases:
        assert client.post("/api/v2/precheck", json=payload).status_code == 422


def test_boolean_and_nonfinite_numeric_rejected(client):
    assert (
        client.post(
            "/api/v2/precheck", json={**precheck_payload(), "amount": True}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v2/precheck",
            content=__import__("json").dumps(
                {**precheck_payload(), "amount": float("inf")}
            ),
            headers={"Content-Type": "application/json"},
        ).status_code
        == 422
    )


def test_precheck_idempotent_and_conflicting_retry(client):
    payload = precheck_payload()
    first = client.post("/api/v2/precheck", json=payload).json()
    service = client.app.state.phase4.service
    calls = service.model_score_calls
    retry = client.post("/api/v2/precheck", json=payload)
    assert retry.status_code == 200
    assert retry.json()["decision"] == first["decision"]
    assert retry.json()["device_state_version"] == first["device_state_version"]
    assert retry.json()["idempotent_replay"] is True
    assert service.model_score_calls == calls
    conflict = client.post(
        "/api/v2/precheck", json={**payload, "amount": payload["amount"] + 1}
    )
    assert conflict.status_code == 409


def test_outcome_idempotency_conflict_and_past_decision_immutable(client):
    original = client.post("/api/v2/precheck", json=precheck_payload()).json()
    payload = outcome_payload()
    first = client.post("/api/v2/outcomes", json=payload)
    assert first.status_code == 200
    retry = client.post("/api/v2/outcomes", json=payload)
    assert retry.status_code == 200
    assert retry.json()["idempotent_replay"] is True
    conflict = client.post(
        "/api/v2/outcomes",
        json={**payload, "authorization_result": "approved", "decline_reason": None},
    )
    assert conflict.status_code == 409
    saved = client.get("/api/v2/runtime/decisions").json()["items"][0]
    assert saved["decision"] == original["decision"]


def test_late_event_rejected(client, base_time):
    assert (
        client.post(
            "/api/v2/precheck", json=precheck_payload(2, base=base_time)
        ).status_code
        == 200
    )
    late = client.post("/api/v2/precheck", json=precheck_payload(1, base=base_time))
    assert late.status_code == 409
    assert late.json()["error"] == "causal_ordering_error"
