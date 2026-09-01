"""Mixed merchant-traffic API: causal ordering, run scoping, ground-truth
isolation.

Everything here drives the real app factory and the real shared
FraudDetectionService. There is no second scoring path, and nothing below
asserts an expected decision for a given scenario -- the point is that the
detector's decisions are discovered by running it, then attributed
afterwards.
"""

from __future__ import annotations

import json

import pytest

from card_testing_sentinel.services.scenario_generation import SCENARIO_CATALOG
from card_testing_sentinel.services.traffic_simulation import (
    ATTACKER_COUNT_RANGE,
    DEVICE_COUNT_RANGE,
)


def _run_to_completion(client, seed: int | None = None) -> tuple[str, list[dict], dict]:
    body = {} if seed is None else {"seed": seed}
    start = client.post("/api/demo/traffic/start", json=body)
    assert start.status_code == 200, start.text
    run_id = start.json()["traffic_run_id"]
    payments: list[dict] = []
    body = start.json()
    for _ in range(start.json()["total_payments"] + 5):
        response = client.post(
            "/api/demo/traffic/step", json={"traffic_run_id": run_id}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        if body.get("payment"):
            payments.append(body["payment"])
        if body["complete"]:
            break
    assert body["complete"]
    return run_id, payments, body


def test_start_contract(client):
    body = client.post("/api/demo/traffic/start", json={}).json()
    assert set(body) == {
        "traffic_run_id",
        "seed",
        "total_payments",
        "device_count",
        "position",
        "run_totals",
        "clock",
    }
    assert body["total_payments"] > 0
    assert DEVICE_COUNT_RANGE[0] <= body["device_count"] <= DEVICE_COUNT_RANGE[1]
    assert 0 <= body["seed"] < 2**31
    assert body["run_totals"] == {"payments": 0, "allow": 0, "review": 0, "block": 0}
    # The clock is virtual and the response says so, so the UI has no excuse
    # to render wall-clock time next to compressed offsets.
    assert "virtual" in body["clock"]


def test_a_full_run_never_trips_the_global_causal_ordering_check(client):
    """Interleaving many devices onto one clock is the whole risk of mixed
    traffic: `_assert_not_late` compares a *global* (timestamp,
    event_sequence). A regression here surfaces as HTTP 409, so a clean run
    is the assertion."""
    _run_id, payments, final = _run_to_completion(client)
    assert len(payments) == final["total_payments"]
    assert final["run_totals"]["payments"] == len(payments)


def test_virtual_offsets_are_non_decreasing_across_the_whole_feed(client):
    _run_id, payments, _final = _run_to_completion(client)
    offsets = [row["virtual_offset_seconds"] for row in payments]
    assert offsets == sorted(offsets)


def test_run_totals_are_scoped_to_this_run_and_match_the_decisions(client):
    """Counters describe the current traffic run, not lifetime database
    volume, and are produced by the run itself rather than derived from a
    capped decisions listing."""
    _run_id, payments, final = _run_to_completion(client)
    counted = {"allow": 0, "review": 0, "block": 0}
    for row in payments:
        counted[row["operations"]["decision"]] += 1
    totals = final["run_totals"]
    assert totals["payments"] == len(payments)
    for action, value in counted.items():
        assert totals[action] == value
    assert sum(counted.values()) == totals["payments"]


def test_a_second_run_starts_its_counters_from_zero(client):
    _first_id, first_payments, _first = _run_to_completion(client)
    assert first_payments
    second = client.post("/api/demo/traffic/start", json={}).json()
    assert second["run_totals"] == {"payments": 0, "allow": 0, "review": 0, "block": 0}


def test_every_run_hides_a_bounded_number_of_attackers(client):
    """A run always has something to find, and never so much that the mix
    stops looking like a merchant's traffic."""
    run_id, _payments, _final = _run_to_completion(client)
    truth = client.post(
        "/api/demo/traffic/truth", json={"traffic_run_id": run_id}
    ).json()
    attackers = [device for device in truth["devices"] if device["is_attack"]]
    assert ATTACKER_COUNT_RANGE[0] <= len(attackers) <= ATTACKER_COUNT_RANGE[1]
    assert len(attackers) < len(truth["devices"]) / 2


def test_a_seed_reproduces_a_run_and_no_seed_varies_it(client):
    """The console must not replay the same movie every time -- that was the
    regression this seeding exists to fix -- while a named seed must still
    bring one run back for inspection."""

    def fingerprint(seed=None):
        run_id, payments, _final = _run_to_completion(client, seed)
        truth = client.post(
            "/api/demo/traffic/truth", json={"traffic_run_id": run_id}
        ).json()
        return (
            len(payments),
            tuple(
                (d["device_key"], d["scenario"], d["first_block_attempt"])
                for d in truth["devices"]
            ),
        )

    assert fingerprint(seed=4242) == fingerprint(seed=4242)
    assert fingerprint(seed=4242) != fingerprint(seed=8888)
    assert len({fingerprint() for _ in range(6)}) > 1


def test_each_device_gets_its_own_causal_history(client):
    _run_id, payments, _final = _run_to_completion(client)
    per_device: dict[str, list[int]] = {}
    for row in payments:
        per_device.setdefault(row["device_key"], []).append(row["attempt"])
    assert DEVICE_COUNT_RANGE[0] <= len(per_device) <= DEVICE_COUNT_RANGE[1]
    for attempts in per_device.values():
        assert attempts == list(range(1, len(attempts) + 1))


def test_no_scenario_label_ever_appears_in_a_payment_response(client):
    """A decision response is what the console renders. If a scenario name
    reached it, the UI could leak the answer even though the engine never
    saw it."""
    _run_id, payments, _final = _run_to_completion(client)
    encoded = json.dumps(payments)
    for scenario, spec in SCENARIO_CATALOG.items():
        assert scenario not in encoded
        assert spec["label"] not in encoded


def test_ground_truth_is_a_separate_explicit_call(client):
    """Truth is never a field on a step response. It has to be asked for."""
    run_id, payments, final = _run_to_completion(client)
    assert "simulator_truth" not in final
    assert all("scenario" not in row for row in payments)

    truth = client.post("/api/demo/traffic/truth", json={"traffic_run_id": run_id})
    assert truth.status_code == 200
    body = truth.json()
    assert DEVICE_COUNT_RANGE[0] <= len(body["devices"]) <= DEVICE_COUNT_RANGE[1]
    assert "never a field of PrecheckRequest" in body["disclosure"]
    for device in body["devices"]:
        assert device["scenario"] in SCENARIO_CATALOG


def test_revealed_truth_matches_the_decisions_that_were_already_made(client):
    """The reveal only attributes; it must not re-derive or re-score."""
    run_id, payments, _final = _run_to_completion(client)
    truth = client.post(
        "/api/demo/traffic/truth", json={"traffic_run_id": run_id}
    ).json()
    observed: dict[str, list[str]] = {}
    for row in payments:
        observed.setdefault(row["device_key"], []).append(row["operations"]["decision"])
    for device in truth["devices"]:
        assert device["actions"] == observed[device["device_key"]]
        assert device["payments_scored"] == len(observed[device["device_key"]])
        expected_review = next(
            (
                index + 1
                for index, action in enumerate(device["actions"])
                if action in ("review", "block")
            ),
            None,
        )
        expected_block = next(
            (
                index + 1
                for index, action in enumerate(device["actions"])
                if action == "block"
            ),
            None,
        )
        assert device["first_review_attempt"] == expected_review
        assert device["first_block_attempt"] == expected_block
        assert device["detected"] is (expected_review is not None)


def test_traffic_step_forbids_extra_fields(client):
    """The step contract must not become a smuggling route for a hint."""
    run_id = client.post("/api/demo/traffic/start", json={}).json()["traffic_run_id"]
    response = client.post(
        "/api/demo/traffic/step",
        json={"traffic_run_id": run_id, "scenario": "burst_attacker"},
    )
    assert response.status_code == 422
    assert response.json()["error"] == "invalid_request"


def test_unknown_traffic_run_is_a_404(client):
    for path in ("/api/demo/traffic/step", "/api/demo/traffic/truth"):
        response = client.post(path, json={"traffic_run_id": "traffic_missing"})
        assert response.status_code == 404


def test_blocked_payments_suppress_authorization_and_create_no_outcome(client):
    _run_id, payments, _final = _run_to_completion(client)
    blocked = [row for row in payments if row["operations"]["decision"] == "block"]
    assert blocked, "the default mix is expected to produce at least one block"
    for row in blocked:
        assert row["operations"]["authorization"] == "suppressed"
        assert row["operations"]["outcome_status"] is None
        assert row["operations"]["checkout_status"] is None


def test_later_payments_are_still_scored_after_an_earlier_block(client):
    """A block is a decision about one request, never a permanent ban."""
    _run_id, payments, _final = _run_to_completion(client)
    per_device: dict[str, list[dict]] = {}
    for row in payments:
        per_device.setdefault(row["device_key"], []).append(row)
    blocked_then_more = [
        rows
        for rows in per_device.values()
        if any(r["operations"]["decision"] == "block" for r in rows)
        and rows.index(next(r for r in rows if r["operations"]["decision"] == "block"))
        < len(rows) - 1
    ]
    assert (
        blocked_then_more
    ), "expected an attacker device blocked before its last attempt"
    for rows in blocked_then_more:
        first_block = next(
            index
            for index, r in enumerate(rows)
            if r["operations"]["decision"] == "block"
        )
        for later in rows[first_block + 1 :]:
            assert later["operations"]["decision"] in {"allow", "review", "block"}
            assert later["operations"]["state_version"] > 0


def test_outcomes_land_after_the_decision_they_belong_to(client):
    """A payment is decided before its processor outcome exists. Lifecycle
    updates therefore arrive on a *later* step than the payment they patch --
    that lag is the causal separation, not a rendering delay."""
    run_id = client.post("/api/demo/traffic/start", json={}).json()["traffic_run_id"]
    first = client.post(
        "/api/demo/traffic/step", json={"traffic_run_id": run_id}
    ).json()
    assert first["lifecycle_updates"] == []
    assert first["payment"]["operations"]["outcome_status"] is None

    saw_update = False
    for _ in range(20):
        body = client.post(
            "/api/demo/traffic/step", json={"traffic_run_id": run_id}
        ).json()
        if body["lifecycle_updates"]:
            saw_update = True
            break
        if body["complete"]:
            break
    assert saw_update, "processor outcomes should land on a later virtual tick"


def test_traffic_uses_the_real_shared_service_and_persists(client):
    before = client.get("/api/system").json()["database"]["requests"]
    _run_id, payments, _final = _run_to_completion(client)
    after = client.get("/api/system").json()["database"]["requests"]
    assert after == before + len(payments)


def test_reset_clears_traffic_runs_without_touching_persistence(client):
    run_id, payments, _final = _run_to_completion(client)
    persisted = client.get("/api/system").json()["database"]["requests"]
    assert client.post("/api/demo/reset", json={}).status_code == 200
    assert (
        client.post(
            "/api/demo/traffic/step", json={"traffic_run_id": run_id}
        ).status_code
        == 404
    )
    assert client.get("/api/system").json()["database"]["requests"] == persisted
    assert payments


@pytest.mark.parametrize(
    "field", ["risk_score", "risk_band", "reason_codes", "evidence"]
)
def test_every_payment_carries_the_allowlisted_projection(client, field):
    _run_id, payments, _final = _run_to_completion(client)
    for row in payments:
        assert field in row["operations"]


def test_no_derived_causal_feature_leaves_the_backend_beyond_the_allowlist(client):
    """The console may show the six allowlisted causal signals and nothing
    else from the derived feature vector.

    Fields the *merchant supplied on the request* are excluded from this
    check: `campaign_active` is both a PrecheckRequest input and a model
    feature, so echoing it back on a payment row discloses nothing the
    caller did not already send. Everything the engine *derives* from
    committed history is what must stay server-side.
    """
    from card_testing_sentinel.api.contracts import PrecheckRequest
    from card_testing_sentinel.features.specification import MODEL_FEATURES
    from card_testing_sentinel.services.operations_projection import (
        SAFE_EVIDENCE_FEATURES,
    )

    request_inputs = set(PrecheckRequest.model_fields)
    assert "campaign_active" in request_inputs  # the documented exclusion

    derived = [
        name
        for name in MODEL_FEATURES
        if name not in SAFE_EVIDENCE_FEATURES and name not in request_inputs
    ]
    assert len(derived) >= 15, "the exclusion set must stay narrow"

    _run_id, payments, _final = _run_to_completion(client)
    encoded = json.dumps(payments)
    leaked = [name for name in derived if f'"{name}"' in encoded]
    assert leaked == []
