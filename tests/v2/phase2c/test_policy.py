from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from card_testing_sentinel.v2.phase2c.policy import (
    PolicyState,
    StatefulPolicy,
    enumerate_candidates,
)
from card_testing_sentinel.v2.phase2c.replay import (
    candidate_metrics,
    fold_stability,
    selection_key,
)


def _candidate(family="persistent_ml", **changes):
    candidate = {
        "candidate_id": "fixture_001",
        "family": family,
        "review_rule_score": 99,
        "block_rule_score": 99,
        "high_window_hours": 336,
        "half_life_hours": 24,
        "recent_request_limit": 16,
        "strong_threshold": 0.8,
        "checkout_risk_multiplier": 0.5,
        "stable_retry_risk_multiplier": 0.8,
        "campaign_threshold_increment": 0.1,
        "campaign_extra_evidence": 1,
        "review_threshold": 0.5,
        "review_high_count": 3,
        "block_threshold": 0.7,
        "block_high_count": 4,
        "block_evidence": 0,
    }
    candidate.update(changes)
    return candidate


def _snapshot(**changes):
    values = {
        "campaign_active": 0,
        "prior_successful_checkouts": 0,
        "same_card_retry_ratio_24h": 0,
        "amount_delta_from_previous": 10,
        "prior_attempts_24h": 2,
        "distinct_cards_14d": 1,
        "card_switches_after_decline_24h": 0,
        "sessions_7d": 1,
        "cross_session_cards_7d": 1,
        "ip_changes_24h": 0,
        "prospective_requests_60s": 0,
        "prior_attempts_5m": 0,
        "distinct_cards_24h": 1,
        "prior_decline_streak": 0,
        "prior_attempts_7d": 2,
        "requests_per_ip_5m": 0,
        "near_minimum_ratio_24h": 0,
    }
    values.update(changes)
    return values


def _decide(policy, index, score, snapshot=None, *, hours=0, session="s1"):
    return policy.decide(
        device_id="device",
        event_id=f"event_{index}",
        timestamp=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=hours),
        session_id=session,
        probability=score,
        snapshot=snapshot or _snapshot(),
    )


def test_accumulation_consecutive_and_block_semantics(tmp_path: Path):
    policy = StatefulPolicy(_candidate())
    assert _decide(policy, 1, 0.8).action == "allow"
    assert _decide(policy, 2, 0.8).action == "allow"
    assert _decide(policy, 3, 0.8).action == "review"
    decision = _decide(policy, 4, 0.8)
    assert decision.action == "block"
    assert decision.high_risk_count == 4
    assert "persistent_high_model_risk" in decision.reason_codes
    encoded = policy.serialize()
    path = tmp_path / "state.json"
    path.write_text(encoded)
    restored = StatefulPolicy.deserialize(path.read_text())
    assert restored.serialize() == encoded


def test_risk_decay_checkout_and_stable_retry_protection():
    policy = StatefulPolicy(_candidate(review_high_count=99, block_high_count=99))
    first = _decide(policy, 1, 0.8)
    decayed = _decide(policy, 2, 0.0, hours=24)
    assert decayed.accumulated_risk == pytest.approx(first.accumulated_risk / 2)
    protected = _decide(
        policy,
        3,
        0.0,
        hours=24,
        snapshot=_snapshot(prior_successful_checkouts=1),
    )
    assert "successful_checkout_risk_reduction" in protected.reason_codes
    stable = _decide(
        policy,
        4,
        0.0,
        hours=24,
        snapshot=_snapshot(
            prior_successful_checkouts=1,
            same_card_retry_ratio_24h=0.9,
            amount_delta_from_previous=1,
        ),
    )
    assert "stable_retry_risk_reduction" in stable.reason_codes


def test_checkout_protection_is_temporary_not_an_allowlist():
    candidate = _candidate(
        family="checkout_protected",
        review_high_count=1,
        block_high_count=99,
        checkout_risk_multiplier=0.5,
    )
    policy = StatefulPolicy(candidate)
    checkout = _snapshot(prior_successful_checkouts=1)
    assert _decide(policy, 1, 0.8, checkout).action == "allow"
    assert _decide(policy, 2, 0.8, checkout).action == "allow"
    assert _decide(policy, 3, 0.8, checkout).action == "allow"
    assert _decide(policy, 4, 0.8, checkout).action == "review"


def test_campaign_adjustment_and_long_term_corroboration():
    candidate = _candidate(
        family="long_term_corroborated",
        review_high_count=2,
        review_evidence=2,
        block_high_count=3,
        block_evidence=2,
    )
    policy = StatefulPolicy(candidate)
    evidence = _snapshot(
        distinct_cards_14d=3,
        card_switches_after_decline_24h=1,
        sessions_7d=2,
        cross_session_cards_7d=2,
        ip_changes_24h=1,
    )
    assert _decide(policy, 1, 0.8, evidence).action == "allow"
    assert _decide(policy, 2, 0.8, evidence, session="s2").action == "review"
    assert _decide(policy, 3, 0.8, evidence, session="s2").action == "block"
    campaign = StatefulPolicy(candidate)
    adjusted = _decide(
        campaign,
        1,
        0.55,
        _snapshot(campaign_active=1, distinct_cards_14d=3),
    )
    assert adjusted.action == "allow"
    assert "campaign_threshold_adjustment" in adjusted.reason_codes


def test_consecutive_logic_resets_and_multiple_sessions():
    candidate = _candidate(
        family="consecutive_high",
        review_consecutive=2,
        block_consecutive=3,
    )
    policy = StatefulPolicy(candidate)
    assert _decide(policy, 1, 0.8, session="s1").action == "allow"
    assert _decide(policy, 2, 0.1, session="s2").action == "allow"
    assert _decide(policy, 3, 0.8, session="s2").action == "allow"
    assert _decide(policy, 4, 0.8, session="s2").action == "review"
    assert policy.state_for("device").sessions == ["s1", "s2"]


def test_timestamp_tie_idempotency_late_and_conflicting_events():
    policy = StatefulPolicy(_candidate())
    decision = _decide(policy, 1, 0.8)
    assert _decide(policy, 1, 0.8) == decision
    with pytest.raises(ValueError, match="conflicting"):
        _decide(policy, 1, 0.7)
    _decide(policy, 2, 0.8, hours=2)
    with pytest.raises(ValueError, match="late"):
        _decide(policy, 3, 0.8, hours=1)


def test_state_schema_refuses_drift():
    payload = PolicyState().to_dict()
    payload["schema_version"] = "wrong"
    with pytest.raises(ValueError, match="unsupported"):
        PolicyState.from_dict(payload)


def test_candidate_enumeration_is_deterministic_and_bounded(tmp_path: Path):
    root = Path(__file__).resolve().parents[3]
    config = yaml.safe_load((root / "configs/v2/phase2c/policy.yaml").read_text())
    first = enumerate_candidates(config)
    second = enumerate_candidates(config)
    assert first == second
    assert len(first) == 20
    assert {row["family"] for row in first} == {
        "rules_only",
        "persistent_ml",
        "consecutive_high",
        "accumulated_decay",
        "long_term_corroborated",
        "campaign_aware",
        "checkout_protected",
    }
    too_many = dict(config)
    too_many["candidate_grid"] = {"rules_only": [{}] * 121}
    with pytest.raises(ValueError, match="limit"):
        enumerate_candidates(too_many)


def _device_rows():
    rows = []
    scenarios = [
        ("normal_standard", 0, None),
        ("normal_bad_luck", 0, None),
        ("flash_standard", 0, None),
        ("flash_hard_retry", 0, None),
        ("attack_burst", 1, "burst"),
        ("attack_evasive", 1, "evasive"),
        ("attack_patient", 1, "patient"),
    ]
    for scenario, label, subtype in scenarios:
        for index in range(100):
            acted = bool(label)
            rows.append(
                {
                    "device_id": f"{scenario}_{index}",
                    "label": label,
                    "population": "attack" if label else "normal",
                    "attack_subtype": subtype,
                    "scenario_tag": scenario,
                    "review_or_higher": acted,
                    "blocked": acted,
                    "first_review_or_higher_request": 2 if acted else float("nan"),
                    "first_block_request": 3 if acted else float("nan"),
                    "requests_scored_through_first_action": 2,
                    "authorizations_processed_before_first_action": 1,
                    "distinct_cards_requested_through_first_action": 2,
                    "distinct_cards_processed_before_first_action": 1,
                    "seconds_to_first_review": 10,
                    "potentially_preventable_later_requests_upper_bound": 0,
                }
            )
    import pandas as pd

    return pd.DataFrame(rows)


def test_safety_effectiveness_rejections_tie_break_and_zero_feasible():
    devices = _device_rows()
    rates = {
        name: {"review_or_higher_rate": 0.05, "block_rate": 0.02}
        for name in (
            "overall_legitimate",
            "normal_standard",
            "normal_bad_luck",
            "flash_standard",
            "flash_hard_retry",
        )
    }
    targets = {
        "overall_review_or_higher": 0.7,
        "overall_block": 0.5,
        "burst_review_or_higher": 0.9,
        "evasive_review_or_higher": 0.5,
        "patient_review_or_higher": 0.4,
    }
    passed = candidate_metrics(devices, rates, targets)
    assert passed["feasible"]
    devices.loc[devices.device_id.eq("normal_standard_0"), "blocked"] = True
    rates["normal_standard"]["block_rate"] = 0
    rejected = candidate_metrics(devices, rates, targets)
    assert not rejected["safety_passed"]
    devices.loc[devices.label.eq(1), ["review_or_higher", "blocked"]] = False
    ineffective = candidate_metrics(devices, rates, targets)
    assert not ineffective["effectiveness_passed"]
    assert not [item for item in [ineffective] if item["feasible"]]
    key_a = selection_key(_candidate(candidate_id="a"), passed)
    key_b = selection_key(_candidate(candidate_id="b"), passed)
    assert key_a < key_b


def test_fold_stability_rejects_one_strong_fold():
    devices = _device_rows()
    rates = {
        name: {"review_or_higher_rate": 1, "block_rate": 1}
        for name in (
            "overall_legitimate",
            "normal_standard",
            "normal_bad_luck",
            "flash_standard",
            "flash_hard_retry",
        )
    }
    targets = {
        "overall_review_or_higher": 0,
        "overall_block": 0,
        "burst_review_or_higher": 0,
        "evasive_review_or_higher": 0,
        "patient_review_or_higher": 0,
    }
    good = candidate_metrics(devices, rates, targets)
    weak_devices = devices.copy()
    weak_devices.loc[weak_devices.label.eq(1), ["review_or_higher", "blocked"]] = False
    weak = candidate_metrics(weak_devices, rates, targets)
    spec = {
        "minimum_overall_review_or_higher": 0.55,
        "minimum_overall_block": 0.35,
        "minimum_burst_review_or_higher": 0.75,
        "minimum_evasive_review_or_higher": 0.3,
        "minimum_patient_review_or_higher": 0.25,
        "maximum_overall_review_range": 0.35,
    }
    result = fold_stability(
        [{"fold": 0, "metrics": good}, {"fold": 1, "metrics": weak}], spec
    )
    assert not result["passed"]
