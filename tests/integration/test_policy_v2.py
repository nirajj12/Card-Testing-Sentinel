"""Policy v2: decisions, evidence boundaries, gate behaviour, isolation."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from card_testing_sentinel.features.specification_v2 import MODEL_FEATURES_V2
from card_testing_sentinel.ml.policy_search_v2 import (
    campaign_adjustment_earns_its_place,
    candidate_configs_v2,
    constraint_failures,
    decide_vector,
    rank_key,
    scenario_rate_caps,
    select,
)
from card_testing_sentinel.policy.engine_v2 import RiskPolicyV2
from card_testing_sentinel.policy.evidence_v2 import (
    evidence_codes_v2,
    trust_codes,
)
from card_testing_sentinel.policy.reasons_v2 import REASON_CODES_V2
from pipelines.select_policy_v2 import write_resolved_policy_config

pytestmark = pytest.mark.slow

ROOT = Path(__file__).resolve().parents[2]
POLICY_DIR = ROOT / "artifacts/policy_v2"
EVAL = ROOT / "artifacts/evaluation"
NOW = datetime(2026, 9, 1, tzinfo=UTC)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def record() -> dict:
    return json.loads((POLICY_DIR / "operational_policy_v2.json").read_text())


@pytest.fixture(scope="module")
def policy(record) -> RiskPolicyV2:
    keys = (
        "family",
        "review_threshold",
        "block_threshold",
        "block_evidence",
        "evidence_set",
        "trust_suppression",
        "block_ttl_seconds",
        "campaign_review_increment",
        "campaign_block_increment",
        "degraded_review_rule_score",
        "degraded_block_rule_score",
    )
    return RiskPolicyV2({key: record[key] for key in keys})


def snapshot(**overrides) -> dict:
    base = dict.fromkeys(MODEL_FEATURES_V2, 0.0)
    base["requests_10s"] = 1.0
    base["requests_24h"] = 1.0
    base["requests_7d"] = 1.0
    base["active_day_count_7d"] = 1.0
    base.update(overrides)
    return base


# --- the three actions ------------------------------------------------------


def test_a_quiet_request_is_allowed(policy):
    decision = policy.decide(snapshot=snapshot(), risk_score=0.05, timestamp=NOW)
    assert decision.action == "allow"
    assert decision.reason_codes == ()
    assert decision.block_expires_at is None


def test_a_high_score_without_evidence_is_reviewed_not_blocked(policy):
    decision = policy.decide(snapshot=snapshot(), risk_score=0.99, timestamp=NOW)
    assert decision.action == "review"
    assert "block_withheld_insufficient_evidence" in decision.reason_codes


def test_a_high_score_with_evidence_is_blocked(policy):
    corroborated = snapshot(
        recent_failures_24h=3.0, decline_streak=3.0, failures_7d=4.0
    )
    decision = policy.decide(snapshot=corroborated, risk_score=0.99, timestamp=NOW)
    assert decision.action == "block"
    assert "elevated_model_risk" in decision.reason_codes
    assert decision.block_expires_at == NOW + timedelta(
        seconds=policy.block_ttl.total_seconds()
    )


def test_the_score_boundary_is_inclusive(policy):
    corroborated = snapshot(
        recent_failures_24h=3.0, decline_streak=3.0, failures_7d=4.0
    )
    just_under = policy.decide(
        snapshot=corroborated,
        risk_score=policy.review_threshold - 1e-9,
        timestamp=NOW,
    )
    exactly = policy.decide(
        snapshot=corroborated, risk_score=policy.review_threshold, timestamp=NOW
    )
    assert just_under.action == "allow"
    assert exactly.action == "review"
    assert (
        policy.decide(
            snapshot=corroborated,
            risk_score=policy.block_threshold,
            timestamp=NOW,
        ).action
        == "block"
    )


def test_every_emitted_reason_code_is_contracted(policy):
    corroborated = snapshot(
        recent_failures_24h=3.0,
        decline_streak=3.0,
        failures_7d=4.0,
        active_day_count_7d=4.0,
        requests_7d=8.0,
        customer_failures_7d=3.0,
        customer_distinct_devices_7d=3.0,
        customer_id_present=1.0,
    )
    decision = policy.decide(snapshot=corroborated, risk_score=0.99, timestamp=NOW)
    assert set(decision.reason_codes) <= set(REASON_CODES_V2)


# --- evidence semantics -----------------------------------------------------


def test_missing_customer_identity_is_never_evidence():
    """`customer_id_present == 0` must not raise risk on its own."""
    guest = snapshot(customer_id_present=0.0)
    assert evidence_codes_v2(guest, "v2_full") == []
    signed_in = snapshot(customer_id_present=1.0)
    assert evidence_codes_v2(signed_in, "v2_full") == []


def test_device_count_alone_is_never_block_evidence():
    """Dataset v3 contains legitimate two- and three-device customers."""
    legitimate_multi_device = snapshot(
        customer_id_present=1.0, customer_distinct_devices_7d=3.0
    )
    assert evidence_codes_v2(legitimate_multi_device, "v2_full") == []
    with_failures = snapshot(
        customer_id_present=1.0,
        customer_distinct_devices_7d=3.0,
        customer_failures_7d=1.0,
    )
    assert "account_device_spread_with_failures" in evidence_codes_v2(
        with_failures, "v2_full"
    )


def test_a_legitimate_multi_device_customer_is_not_blocked(policy):
    """The exact false-positive case the evidence design exists to avoid."""
    shopper = snapshot(
        customer_id_present=1.0,
        customer_distinct_devices_7d=3.0,
        customer_successful_checkouts_30d=4.0,
        customer_age_seconds=60 * 86400.0,
    )
    assert policy.decide(snapshot=shopper, risk_score=0.99, timestamp=NOW).action == (
        "review"
    )


def test_a_cross_device_campaign_reaches_block_evidence():
    campaign = snapshot(
        customer_id_present=1.0,
        customer_distinct_devices_7d=5.0,
        customer_failures_7d=4.0,
    )
    codes = evidence_codes_v2(campaign, "v2_full")
    assert "account_failures_across_devices" in codes
    assert "account_device_spread_with_failures" in codes
    assert len(codes) >= 2


def test_long_horizon_evidence_exists_for_a_patient_attacker():
    """v1's gate was five-sixths 24h-windowed, so a patient device could
    never accumulate corroboration however high it scored."""
    patient = snapshot(
        requests_24h=1.0, failures_7d=4.0, active_day_count_7d=5.0, requests_7d=8.0
    )
    assert evidence_codes_v2(patient, "v1_like") == []
    codes = evidence_codes_v2(patient, "v2_long_horizon")
    expected = {
        "sustained_failures_7d",
        "multi_day_activity_7d",
        "sustained_requests_7d",
    }
    assert expected <= set(codes)


def test_evidence_boundaries_are_exact():
    assert "sustained_failures_7d" not in evidence_codes_v2(
        snapshot(failures_7d=2.0), "v2_long_horizon"
    )
    assert "sustained_failures_7d" in evidence_codes_v2(
        snapshot(failures_7d=3.0), "v2_long_horizon"
    )
    assert "account_failures_across_devices" not in evidence_codes_v2(
        snapshot(customer_failures_7d=1.0), "v2_full"
    )
    assert "account_failures_across_devices" in evidence_codes_v2(
        snapshot(customer_failures_7d=2.0), "v2_full"
    )


def test_trust_can_only_soften_a_block_never_an_allow():
    trusting = RiskPolicyV2(
        {
            "family": "evidence_gated_v2",
            "review_threshold": 0.60,
            "block_threshold": 0.80,
            "block_evidence": 1,
            "evidence_set": "v2_full",
            "trust_suppression": "moderate",
            "block_ttl_seconds": 3600,
            "degraded_review_rule_score": 4,
            "degraded_block_rule_score": 6,
        }
    )
    established = snapshot(
        recent_failures_24h=3.0,
        decline_streak=3.0,
        customer_id_present=1.0,
        customer_age_seconds=30 * 86400.0,
    )
    softened = trusting.decide(snapshot=established, risk_score=0.99, timestamp=NOW)
    assert softened.action == "review"
    assert "block_withheld_established_history" in softened.reason_codes
    # trust never turns a review into an allow
    assert (
        trusting.decide(snapshot=established, risk_score=0.65, timestamp=NOW).action
        == "review"
    )
    assert trust_codes(snapshot(), "none") == []


def test_a_genuine_repeated_failure_without_corroboration_is_only_reviewed(policy):
    unlucky = snapshot(recent_failures_24h=2.0, customer_id_present=1.0)
    decision = policy.decide(snapshot=unlucky, risk_score=0.95, timestamp=NOW)
    assert decision.action == "review"


# --- degraded mode ----------------------------------------------------------


def test_a_missing_model_falls_back_to_rules_only(policy):
    quiet = policy.decide(snapshot=snapshot(), risk_score=None, timestamp=NOW)
    assert quiet.action == "allow"
    assert quiet.reason_codes == ("degraded_rules_only",)
    assert quiet.risk_score is None

    noisy = policy.decide(
        snapshot=snapshot(
            requests_60s=6.0,
            requests_5m=8.0,
            decline_streak=3.0,
            sessions_24h=4.0,
            requests_24h=6.0,
        ),
        risk_score=None,
        timestamp=NOW,
    )
    assert noisy.action in ("review", "block")
    assert noisy.reason_codes == ("degraded_rules_only",)
    assert noisy.block_expires_at is None


def test_an_invalid_policy_configuration_fails_closed():
    for broken in (
        {"review_threshold": 0.9, "block_threshold": 0.5},
        {"evidence_set": "nonexistent"},
        {"trust_suppression": "nonexistent"},
        {"family": "threshold"},
    ):
        config = {
            "family": "evidence_gated_v2",
            "review_threshold": 0.6,
            "block_threshold": 0.8,
            "block_evidence": 2,
            "evidence_set": "v2_full",
            "trust_suppression": "none",
            "block_ttl_seconds": 3600,
            "degraded_review_rule_score": 4,
            "degraded_block_rule_score": 6,
            **broken,
        }
        with pytest.raises(ValueError):
            RiskPolicyV2(config)


# --- selection hygiene ------------------------------------------------------


def test_the_artifact_binds_the_frozen_model_and_contract(record):
    metadata = json.loads((ROOT / "artifacts/model_v2/metadata.json").read_text())
    assert record["model_sha256"] == metadata["model_sha256"]
    assert record["model_sha256"] == sha256(
        ROOT / "artifacts/model_v2/risk_model_v2.joblib"
    )
    assert record["feature_contract_sha256"] == metadata["feature_contract_sha256"]
    assert record["policy_config_sha256"] == sha256(ROOT / "configs/policy_v2.yaml")
    assert record["selected_on"] == "Dataset v3 validation split only"
    assert record["blind_evaluated"] is False
    assert record["blind_v2_generated"] is False


def test_final_policy_artifact_sidecar_matches_disk():
    artifact = POLICY_DIR / "operational_policy_v2.json"
    recorded = (POLICY_DIR / "operational_policy_v2.sha256").read_text().split()[0]
    assert recorded == sha256(artifact)


def test_final_config_hash_is_independently_recomputed_from_disk(record):
    config_bytes = (ROOT / "configs/policy_v2.yaml").read_bytes()
    independently_computed = hashlib.sha256(config_bytes).hexdigest()
    assert record["policy_config_sha256"] == independently_computed


def test_resolved_config_writer_replaces_stale_values_before_hashing(tmp_path):
    source = ROOT / "configs/policy_v2.yaml"
    target = tmp_path / "policy_v2.yaml"
    target.write_bytes(source.read_bytes())
    selected = yaml.safe_load(source.read_text())["policy"]
    stale = target.read_text().replace(
        "  review_threshold: 0.75", "  review_threshold: 0.5"
    )
    target.write_text(stale)
    write_resolved_policy_config(target, selected)
    assert yaml.safe_load(target.read_text())["policy"] == selected
    assert sha256(target) == sha256(source)


def test_policy_v1_is_untouched():
    v1 = json.loads((ROOT / "artifacts/policy/operational_policy.json").read_text())
    assert v1["family"] == "evidence_gated"
    assert v1["review_threshold"] == 0.60
    assert v1["block_threshold"] == 0.78
    assert v1["blind_evaluated"] is False
    assert (ROOT / "configs/policy.yaml").is_file()


def test_blind_v1_1_is_untouched():
    import scripts.freeze_blind_benchmark as freeze

    assert freeze.verify() == []
    for name in ("blind_metrics_v2.json", "blind_freeze_manifest_v2.json"):
        assert not (EVAL / name).exists()
    assert (ROOT / "configs/blind_v2.yaml").is_file()
    blind_v2 = json.loads((EVAL / "blind_v2_freeze_manifest.json").read_text())
    assert blind_v2["blind_version"] == "v2"
    assert blind_v2["foundation"]["blind_v1_1_freeze_sha256"] == sha256(
        EVAL / "blind_freeze_manifest.json"
    )


def test_the_selected_policy_satisfies_every_declared_constraint(record):
    config = yaml.safe_load((ROOT / "configs/policy_v2.yaml").read_text())
    scenarios = pd.read_csv(EVAL / "policy_v2_scenarios.csv").set_index("scenario")
    failures = constraint_failures(
        record["validation_metrics"], scenarios, config["policy_constraints"]
    )
    assert failures == []


def test_a_reckless_policy_is_rejected_by_the_constraints():
    """The budget must actually exclude something, or it is decoration."""
    config = yaml.safe_load((ROOT / "configs/policy_v2.yaml").read_text())
    scenarios = pd.read_csv(EVAL / "policy_v2_scenarios.csv").set_index("scenario")
    reckless = {
        "attack_review_or_higher_recall": 0.99,
        "attack_block_recall": 0.95,
        "legitimate_review_or_higher_rate": 0.40,
        "legitimate_block_rate": 0.12,
    }
    assert constraint_failures(reckless, scenarios, config["policy_constraints"])


def test_scenario_guardrail_is_uniform_and_size_aware():
    constraints = yaml.safe_load((ROOT / "configs/policy_v2.yaml").read_text())[
        "policy_constraints"
    ]
    small = scenario_rate_caps(50, constraints)
    large = scenario_rate_caps(500, constraints)
    assert small[0] >= large[0]
    assert small[1] >= large[1]
    assert scenario_rate_caps(100, constraints) == scenario_rate_caps(100, constraints)


def test_the_campaign_rule_drops_a_tolerance_that_costs_blocking():
    """Phase 11 §16: campaign tolerance is not inherited, it must earn its place."""
    with_campaign = pd.Series(
        {
            "attack_review_or_higher_recall": 0.891,
            "attack_block_recall": 0.5278,
            "legitimate_review_or_higher_rate": 0.060,
            "legitimate_block_rate": 0.0089,
        }
    )
    without = pd.Series(
        {
            "attack_review_or_higher_recall": 0.8739,
            "attack_block_recall": 0.5919,
            "legitimate_review_or_higher_rate": 0.053,
            "legitimate_block_rate": 0.0089,
        }
    )
    assert not campaign_adjustment_earns_its_place(with_campaign, without)
    # a tolerance that is better or equal on every axis IS retained
    dominated = pd.Series(
        {
            "attack_review_or_higher_recall": 0.80,
            "attack_block_recall": 0.50,
            "legitimate_review_or_higher_rate": 0.070,
            "legitimate_block_rate": 0.0100,
        }
    )
    assert campaign_adjustment_earns_its_place(with_campaign, dominated)


def test_the_selected_policy_carries_no_campaign_adjustment(record):
    assert record["campaign_review_increment"] == 0.0
    assert record["campaign_block_increment"] == 0.0


def test_select_refuses_when_nothing_is_eligible():
    empty = pd.DataFrame({"eligible": [False], "candidate": ["x"]})
    with pytest.raises(RuntimeError, match="no policy candidate"):
        select(empty)


def test_the_candidate_grid_is_compact_and_ordered():
    config = yaml.safe_load((ROOT / "configs/policy_v2.yaml").read_text())
    candidates = candidate_configs_v2(
        config["policy_search"],
        {
            "block_ttl_seconds": 3600,
            "degraded_review_rule_score": 4,
            "degraded_block_rule_score": 6,
        },
    )
    assert len(candidates) < 1000
    assert all(c["block_threshold"] >= c["review_threshold"] for c in candidates)


def test_policy_evaluation_is_deterministic():
    risk = np.array([0.1, 0.8, 0.95, 0.95])
    campaign = np.array([False, False, False, True])
    evidence = np.array([0, 0, 3, 3])
    trusted = np.array([False, False, False, False])
    config = {
        "review_threshold": 0.75,
        "block_threshold": 0.90,
        "block_evidence": 2,
        "campaign_review_increment": 0.0,
        "campaign_block_increment": 0.0,
    }
    first = decide_vector(risk, campaign, evidence, trusted, config)
    second = decide_vector(risk, campaign, evidence, trusted, config)
    assert list(first) == list(second) == [0, 1, 2, 2]


def test_rank_key_prefers_recall_then_blocking():
    better = pd.Series(
        {
            "attack_review_or_higher_recall": 0.90,
            "attack_block_recall": 0.60,
            "median_first_review_attempt": 4.0,
            "legitimate_review_or_higher_rate": 0.05,
            "evidence_set": "v2_full",
            "block_evidence": 2,
        }
    )
    worse = better.copy()
    worse["attack_review_or_higher_recall"] = 0.80
    assert rank_key(better) < rank_key(worse)


def test_guest_traffic_is_not_blocked_disproportionately(record):
    segments = {row["segment"]: row for row in record["customer_id_segments"]}
    absent = segments["customer_absent"]
    present = segments["customer_present"]
    assert absent["legitimate_block_rate"] <= present["legitimate_block_rate"]
    assert (
        absent["legitimate_review_or_higher_rate"]
        <= (present["legitimate_review_or_higher_rate"])
    )


def test_no_merchant_kind_dominates_the_false_positives(record):
    merchants = pd.DataFrame(record["merchant_friction"])
    assert merchants.legitimate_block_rate.max() < 0.05
    assert merchants.attack_review_or_higher_recall.min() > 0.5


def test_the_device_view_reproduces_the_recorded_summary(record):
    """The published metrics must come from the published decisions."""
    scenarios = pd.read_csv(EVAL / "policy_v2_scenarios.csv")
    attack = scenarios.loc[scenarios.population.eq("attack")]
    legitimate = scenarios.loc[scenarios.population.eq("legitimate")]
    metrics = record["validation_metrics"]
    assert int(attack.devices.sum()) == metrics["attack_devices"]
    assert int(legitimate.devices.sum()) == metrics["legitimate_devices"]
    assert (
        int(legitimate.blocked_devices.sum()) == (metrics["legitimate_blocked_devices"])
    )
    assert (
        int(attack.devices.sum() - attack.reviewed_devices.sum())
        == (metrics["attack_never_detected"])
    )


def test_required_detection_and_gate_diagnostics_are_published(record):
    metrics = record["validation_metrics"]
    assert set(metrics["cumulative_attack_detection"]) == {"1", "2", "3", "5"}
    gate = record["evidence_gate_value"]
    assert gate["score_only_block_candidate_attempts"] == (
        gate["evidence_qualified_block_attempts"]
        + gate["block_attempts_suppressed_by_gate"]
    )
    assert len(record["review_threshold_sweep"]) == 9
    assert len(record["block_threshold_sweep"]) == 4
