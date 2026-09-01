"""Risk-policy behaviour: bands, block evidence, TTL and recovery."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from card_testing_sentinel.common.config import load_config
from card_testing_sentinel.features.specification import MODEL_FEATURES
from card_testing_sentinel.policy.engine import DeviceRiskHistory, RiskPolicy
from card_testing_sentinel.policy.evidence import evidence_codes, evidence_count
from card_testing_sentinel.policy.reasons import REASON_CODES

pytestmark = pytest.mark.slow

ROOT = Path(__file__).resolve().parents[2]
START = datetime(2034, 1, 1, tzinfo=UTC)


@pytest.fixture(scope="module")
def config() -> dict:
    return load_config(ROOT / "configs/policy.yaml")["policy"]


@pytest.fixture(scope="module")
def policy(config) -> RiskPolicy:
    return RiskPolicy(config)


def snapshot(**overrides) -> dict:
    return {**dict.fromkeys(MODEL_FEATURES, 0.0), **overrides}


def corroborated(**overrides) -> dict:
    return snapshot(
        recent_failures_24h=4,
        decline_streak=3,
        sessions_24h=4,
        requests_24h=8,
        **overrides,
    )


# --- bands ------------------------------------------------------------------


def test_below_review_threshold_allows(policy):
    decision = policy.decide(
        snapshot=snapshot(), risk_score=policy.review_threshold - 0.01, timestamp=START
    )
    assert decision.action == "allow"
    assert decision.reason_codes == ()
    assert decision.block_expires_at is None


def test_review_band_reviews(policy):
    decision = policy.decide(
        snapshot=snapshot(), risk_score=policy.review_threshold, timestamp=START
    )
    assert decision.action == "review"
    assert decision.block_expires_at is None


def test_block_band_with_evidence_blocks(policy):
    decision = policy.decide(
        snapshot=corroborated(), risk_score=policy.block_threshold, timestamp=START
    )
    assert decision.action == "block"


def test_the_bands_are_ordered(policy):
    assert 0.0 <= policy.review_threshold < policy.block_threshold <= 1.0


def test_thresholds_must_be_ordered(config):
    with pytest.raises(ValueError, match="review <= block"):
        RiskPolicy({**config, "review_threshold": 0.9, "block_threshold": 0.5})


# --- block safety -----------------------------------------------------------


def test_a_high_score_without_evidence_does_not_block(policy):
    if policy.family == "threshold":
        pytest.skip("the selected family has no evidence gate")
    decision = policy.decide(snapshot=snapshot(), risk_score=1.0, timestamp=START)
    assert decision.action == "review"


def test_a_block_always_carries_an_expiry(policy):
    decision = policy.decide(snapshot=corroborated(), risk_score=1.0, timestamp=START)
    assert decision.action == "block"
    assert decision.block_expires_at == START + policy.block_ttl
    assert policy.block_ttl > timedelta(0)


def test_only_a_block_carries_an_expiry(policy):
    for score in (0.0, policy.review_threshold):
        decision = policy.decide(snapshot=snapshot(), risk_score=score, timestamp=START)
        assert decision.block_expires_at is None


def test_after_the_ttl_a_calm_request_is_allowed_again(policy):
    """A block is temporary. Nothing is permanently labelled fraudulent: a
    later request is scored from current history and can return to allow."""
    blocked = policy.decide(snapshot=corroborated(), risk_score=1.0, timestamp=START)
    assert blocked.action == "block"

    later = blocked.block_expires_at + timedelta(minutes=1)
    recovered = policy.decide(snapshot=snapshot(), risk_score=0.01, timestamp=later)
    assert recovered.action == "allow"
    assert recovered.block_expires_at is None


def test_review_is_not_sticky(policy):
    """Every request is reconsidered from current history -- there is no
    permanent review label."""
    reviewed = policy.decide(
        snapshot=snapshot(), risk_score=policy.review_threshold, timestamp=START
    )
    assert reviewed.action == "review"
    calm = policy.decide(
        snapshot=snapshot(), risk_score=0.0, timestamp=START + timedelta(hours=1)
    )
    assert calm.action == "allow"


# --- evidence ---------------------------------------------------------------


def test_evidence_codes_are_all_in_the_reason_contract():
    codes = evidence_codes(corroborated())
    assert codes
    assert set(codes) <= set(REASON_CODES)


def test_evidence_needs_the_underlying_behaviour():
    assert evidence_count(snapshot()) == 0
    assert evidence_count(corroborated()) >= 2


def test_retry_evidence_requires_declines_to_retry():
    """`rapid_retry_after_decline` is meaningless without declines."""
    without = snapshot(retry_after_decline_ratio_24h=1.0, recent_failures_24h=0)
    assert "rapid_retry_after_decline" not in evidence_codes(without)
    with_declines = snapshot(retry_after_decline_ratio_24h=1.0, recent_failures_24h=3)
    assert "rapid_retry_after_decline" in evidence_codes(with_declines)


def test_a_blocked_decision_explains_itself(policy):
    decision = policy.decide(snapshot=corroborated(), risk_score=1.0, timestamp=START)
    assert decision.action == "block"
    assert "elevated_model_risk" in decision.reason_codes
    # the customer-facing explanation names observable behaviour, not a number
    assert len(decision.reason_codes) > 1
    assert set(decision.reason_codes) <= set(REASON_CODES)


def test_no_uncontracted_reason_code_can_escape(policy):
    for score in (0.0, 0.5, 0.79, 1.0):
        decision = policy.decide(
            snapshot=corroborated(), risk_score=score, timestamp=START
        )
        assert set(decision.reason_codes) <= set(REASON_CODES)


# --- persistent family ------------------------------------------------------


def test_persistent_family_requires_repeated_elevation(config):
    policy = RiskPolicy(
        {
            **config,
            "family": "persistent",
            "block_elevated_count": 2,
            "block_evidence": 0,
        }
    )
    history = DeviceRiskHistory()
    first = policy.decide(
        snapshot=corroborated(), risk_score=1.0, timestamp=START, history=history
    )
    assert first.action == "review", "one elevated attempt must not block"

    history.record(START, 1.0, policy.persistence_window, policy.history_cap)
    second = policy.decide(
        snapshot=corroborated(),
        risk_score=1.0,
        timestamp=START + timedelta(minutes=5),
        history=history,
    )
    assert second.action == "block"
    assert "persistent_elevated_risk" in second.reason_codes


def test_risk_history_forgets_outside_the_window(config):
    policy = RiskPolicy({**config, "family": "persistent", "block_elevated_count": 2})
    history = DeviceRiskHistory()
    history.record(START, 1.0, policy.persistence_window, policy.history_cap)
    stale = START + policy.persistence_window + timedelta(hours=1)
    assert (
        history.elevated_count(
            stale, policy.review_threshold, policy.persistence_window
        )
        == 0
    )


def test_risk_history_is_capped(config):
    policy = RiskPolicy(config)
    history = DeviceRiskHistory()
    for index in range(policy.history_cap * 3):
        history.record(
            START + timedelta(seconds=index),
            0.9,
            policy.persistence_window,
            policy.history_cap,
        )
    assert len(history.recent) <= policy.history_cap


# --- campaign ---------------------------------------------------------------


def test_campaign_tolerance_raises_the_bands_only_during_a_campaign(config):
    policy = RiskPolicy(
        {**config, "campaign_review_increment": 0.05, "campaign_block_increment": 0.02}
    )
    score = policy.review_threshold + 0.01
    off = policy.decide(snapshot=snapshot(), risk_score=score, timestamp=START)
    on = policy.decide(
        snapshot=snapshot(), risk_score=score, timestamp=START, campaign_active=True
    )
    assert off.action == "review"
    assert on.action == "allow", "the same score is tolerated during a sale"


def test_campaign_tolerance_is_recorded_in_the_reasons(config):
    policy = RiskPolicy(
        {**config, "campaign_review_increment": 0.05, "campaign_block_increment": 0.02}
    )
    decision = policy.decide(
        snapshot=snapshot(),
        risk_score=policy.review_threshold + 0.06,
        timestamp=START,
        campaign_active=True,
    )
    assert decision.action == "review"
    assert "campaign_tolerance_applied" in decision.reason_codes


def test_campaign_context_comes_from_the_request_not_the_snapshot(policy):
    """`campaign_active` is a merchant fact on the request; it is not one of
    the 28 causal features and must not be read from the snapshot."""
    assert "campaign_active" not in MODEL_FEATURES
    polluted = snapshot(**{})
    polluted["campaign_active"] = 1.0
    plain = policy.decide(
        snapshot=polluted, risk_score=policy.review_threshold, timestamp=START
    )
    assert plain.action == "review", "a snapshot key must not grant tolerance"


# --- artifact ---------------------------------------------------------------


def test_the_policy_artifact_binds_the_exact_model_and_contract():
    import hashlib

    artifact = json.loads(
        (ROOT / "artifacts/policy/operational_policy.json").read_text()
    )
    from card_testing_sentinel.features.specification import MODEL_FEATURES_SHA256

    assert artifact["feature_contract_sha256"] == MODEL_FEATURES_SHA256
    model_hash = hashlib.sha256(
        (ROOT / "artifacts/model/risk_model.joblib").read_bytes()
    ).hexdigest()
    assert artifact["model_sha256"] == model_hash
    assert artifact["status"] == "validation_selected"
    assert artifact["blind_evaluated"] is False
    assert artifact["selected_on"] == "validation split only"


def test_the_running_policy_matches_the_selected_artifact(config):
    artifact = json.loads(
        (ROOT / "artifacts/policy/operational_policy.json").read_text()
    )
    for key in (
        "family",
        "review_threshold",
        "block_threshold",
        "block_evidence",
        "campaign_review_increment",
        "campaign_block_increment",
        "block_ttl_seconds",
    ):
        assert config[key] == artifact[key], key


def test_the_artifact_records_scenario_and_merchant_friction():
    artifact = json.loads(
        (ROOT / "artifacts/policy/operational_policy.json").read_text()
    )
    legitimate = artifact["legitimate_scenario_friction"]
    attack = artifact["attack_scenario_detection"]
    assert "repeated_genuine_failures" in legitimate
    assert "patient_tester" in attack
    for row in legitimate.values():
        assert row["block_rate"] <= row["review_or_higher_rate"]
    assert artifact["merchant_friction"]
