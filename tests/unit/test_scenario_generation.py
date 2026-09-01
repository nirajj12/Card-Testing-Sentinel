"""Stage 3 unit coverage: deterministic, scenario-specific raw-event shapes.

These tests only exercise card_testing_sentinel.services.scenario_generation
-- pure data, no model, no policy, no persistence -- so they run fast and
pin the exact fixture in tests/fixtures/scenarios/plans.json.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from card_testing_sentinel.services.scenario_generation import (
    SCENARIO_CATALOG,
    SCENARIO_PLANS,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = json.loads((ROOT / "tests/fixtures/scenarios/plans.json").read_text())

ALL_SCENARIOS = (
    "normal_customer",
    "normal_bad_luck",
    "flash_standard",
    "flash_hard_retry",
    "burst_attacker",
    "evasive_attacker",
    "patient_attacker",
)


def test_all_seven_scenarios_are_defined():
    assert set(SCENARIO_PLANS) == set(ALL_SCENARIOS)
    assert set(SCENARIO_CATALOG) == set(ALL_SCENARIOS)


def test_scenario_generation_is_deterministic_across_calls():
    """Calling the module-level generation twice (a fresh import in a
    subprocess is out of scope here, but re-deriving the plan objects
    must be byte-for-byte identical) proves there is no randomness or
    wall-clock dependency anywhere in plan construction. Reloading the
    module rebuilds the PlannedAttempt class too, so instances are
    compared as plain field dicts rather than via dataclass `==` (which
    also checks class identity)."""
    import importlib

    from card_testing_sentinel.services import scenario_generation as module

    reloaded = importlib.reload(module)
    for name in ALL_SCENARIOS:
        reloaded_dicts = [asdict(a) for a in reloaded.SCENARIO_PLANS[name]]
        original_dicts = [asdict(a) for a in SCENARIO_PLANS[name]]
        assert reloaded_dicts == original_dicts
    importlib.reload(module)  # restore the shared module object for other tests


def test_scenario_plans_match_the_deterministic_fixture():
    for name in ALL_SCENARIOS:
        actual = [asdict(attempt) for attempt in SCENARIO_PLANS[name]]
        assert actual == FIXTURE["plans"][name]
    assert SCENARIO_CATALOG == FIXTURE["catalog"]


def test_scenario_catalog_contains_no_expected_decision_or_score_hint():
    forbidden_terms = (
        "decision",
        "action",
        "score",
        "block",
        "review",
        "allow",
        "threshold",
        "expected",
    )
    for _name, spec in SCENARIO_CATALOG.items():
        assert set(spec) == {"label", "attempts"}
        for key in spec:
            assert not any(term in key.lower() for term in forbidden_terms)


def test_scenario_label_never_appears_inside_any_planned_attempt_field():
    """A scenario's own key/label must never leak into any field that ends
    up inside a precheck/outcome/checkout payload (identity suffixes,
    amount, campaign flag, decline reason)."""
    for name, plan in SCENARIO_PLANS.items():
        label = SCENARIO_CATALOG[name]["label"]
        for attempt in plan:
            payload = asdict(attempt)
            encoded = json.dumps(payload)
            assert name not in encoded
            assert label not in encoded


def test_verified_card_metadata_churns_far_more_for_attackers_than_legit():
    """Post-hoc card metadata (last4 the merchant only learns from a
    verified outcome) rotates far more in attacker plans. It is a weak
    supporting signal, not a per-request card identity."""

    def distinct_last4(name: str) -> int:
        return len({a.outcome_card_last4 for a in SCENARIO_PLANS[name]})

    def distinct_sessions(name: str) -> int:
        return len({a.session_suffix for a in SCENARIO_PLANS[name]})

    assert distinct_last4("normal_customer") == 1
    assert distinct_sessions("normal_customer") == 1
    assert distinct_last4("normal_bad_luck") == 2
    assert distinct_sessions("normal_bad_luck") == 1
    assert distinct_last4("flash_standard") == 1

    hard_retry = [a.outcome_card_last4 for a in SCENARIO_PLANS["flash_hard_retry"]]
    assert len(set(hard_retry[:-1])) == 1 and hard_retry[-1] != hard_retry[0]

    assert distinct_last4("burst_attacker") == len(SCENARIO_PLANS["burst_attacker"])
    assert distinct_last4("evasive_attacker") > distinct_last4("normal_bad_luck")
    assert distinct_last4("patient_attacker") > distinct_last4("normal_bad_luck")


def test_burst_attacker_shows_a_new_verified_card_essentially_every_attempt():
    last4 = [a.outcome_card_last4 for a in SCENARIO_PLANS["burst_attacker"]]
    assert len(set(last4)) == len(last4)


def test_evasive_attacker_rotates_verified_cards_selectively_not_every_attempt():
    last4 = [a.outcome_card_last4 for a in SCENARIO_PLANS["evasive_attacker"]]
    assert any(last4[i] == last4[i + 1] for i in range(len(last4) - 1))
    assert 1 < len(set(last4)) < len(last4)


def test_evasive_attacker_gaps_mix_short_and_long_pauses():
    gaps = [a.gap_seconds for a in SCENARIO_PLANS["evasive_attacker"] if a.gap_seconds]
    assert min(gaps) < 60
    assert max(gaps) > 120


def test_patient_attacker_spreads_across_sessions_and_long_gaps():
    plan = SCENARIO_PLANS["patient_attacker"]
    sessions = [a.session_suffix for a in plan]
    assert len(set(sessions)) == len(plan)  # a new session on every attempt
    gaps = [a.gap_seconds for a in plan if a.gap_seconds]
    assert all(gap >= 3600 for gap in gaps)  # hours-scale, not seconds-scale


def test_patient_attacker_is_slower_than_burst_attacker():
    def average_gap(name: str) -> float:
        gaps = [a.gap_seconds for a in SCENARIO_PLANS[name] if a.gap_seconds]
        return sum(gaps) / len(gaps)

    assert average_gap("patient_attacker") > average_gap("evasive_attacker")
    assert average_gap("evasive_attacker") > average_gap("burst_attacker")


def test_flash_hard_retry_gaps_are_faster_than_flash_standard_and_normal():
    def average_gap(name: str) -> float:
        gaps = [a.gap_seconds for a in SCENARIO_PLANS[name] if a.gap_seconds]
        return sum(gaps) / len(gaps)

    assert average_gap("flash_hard_retry") < average_gap("flash_standard")
    assert average_gap("flash_standard") < average_gap("normal_customer")


def test_legitimate_scenarios_end_approved_attacker_scenarios_never_approve():
    legitimate = (
        "normal_customer",
        "normal_bad_luck",
        "flash_standard",
        "flash_hard_retry",
    )
    for name in legitimate:
        plan = SCENARIO_PLANS[name]
        assert plan[-1].authorization_result == "approved"
        assert all(a.authorization_result == "declined" for a in plan[:-1])

    for name in ("burst_attacker", "evasive_attacker", "patient_attacker"):
        assert all(a.authorization_result == "declined" for a in SCENARIO_PLANS[name])


def test_only_flash_scenarios_are_campaign_active():
    for name, plan in SCENARIO_PLANS.items():
        expected = name in ("flash_standard", "flash_hard_retry")
        assert all(a.campaign_active is expected for a in plan), name
