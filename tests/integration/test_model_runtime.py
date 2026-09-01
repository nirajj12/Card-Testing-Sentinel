"""The runtime loads the trained model, and the failover is explicit.

`degraded_rules_only` exists so a missing artifact cannot take the service
down, but it must never activate silently: it is visible in `/api/system`,
in the precheck response and in the reason codes.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from card_testing_sentinel.api.contracts import OutcomeRequest, PrecheckRequest
from card_testing_sentinel.features.specification import (
    MODEL_FEATURES,
    MODEL_FEATURES_SHA256,
)
from card_testing_sentinel.modeling.model import (
    DEGRADED,
    READY,
    ModelContractError,
    RiskModel,
)
from card_testing_sentinel.modeling.registry import ArtifactRegistry
from card_testing_sentinel.persistence.memory_repository import InMemoryStateRepository
from card_testing_sentinel.policy.engine import RiskPolicy
from card_testing_sentinel.security.identifiers import IdentifierProtector
from card_testing_sentinel.services.risk_service import RiskService
from tests.helpers import precheck_payload

ROOT = Path(__file__).resolve().parents[2]
START = datetime(2033, 1, 1, tzinfo=UTC)


def test_the_trained_artifact_loads_and_matches_the_feature_contract():
    model = RiskModel.load(ROOT)
    assert model.status == READY
    assert model.available
    assert model.description["family"] in {
        "logistic_regression",
        "hist_gradient_boosting",
    }


def test_the_model_scores_a_snapshot_to_a_finite_probability():
    model = RiskModel.load(ROOT)
    snapshot = dict.fromkeys(MODEL_FEATURES, 0.0)
    score = model.score(snapshot)
    assert score is not None
    assert 0.0 <= score <= 1.0


def test_scoring_depends_only_on_the_contract_features():
    """Extra keys in the snapshot -- labels included -- cannot change a score,
    because only the ordered contract is read."""
    model = RiskModel.load(ROOT)
    snapshot = dict.fromkeys(MODEL_FEATURES, 1.0)
    baseline = model.score(snapshot)
    polluted = {
        **snapshot,
        "label": 1,
        "scenario": "fast_burst",
        "population": "attack",
    }
    assert model.score(polluted) == baseline


def test_feature_order_changes_the_score_so_order_is_load_bearing():
    model = RiskModel.load(ROOT)
    ascending = {name: float(i) for i, name in enumerate(MODEL_FEATURES)}
    descending = {
        name: float(len(MODEL_FEATURES) - i) for i, name in enumerate(MODEL_FEATURES)
    }
    assert model.score(ascending) != model.score(descending)


def test_a_missing_artifact_degrades_explicitly_rather_than_faking_a_score(tmp_path):
    model = RiskModel.load(tmp_path)
    assert model.status == DEGRADED
    assert not model.available
    assert model.score(dict.fromkeys(MODEL_FEATURES, 0.0)) is None
    assert "no trained model artifact" in model.degraded_reason


def test_degrading_can_be_refused_outright(tmp_path):
    with pytest.raises(ModelContractError):
        RiskModel.load(tmp_path, allow_degraded=False)


def test_a_mismatched_feature_contract_is_refused_not_silently_served(tmp_path):
    import joblib

    from card_testing_sentinel.ml.training import RiskModelArtifact

    artifact = RiskModelArtifact(
        model=None,
        family="logistic_regression",
        parameters={},
        calibration_method="none",
        calibrator=None,
        feature_names=MODEL_FEATURES,
        feature_contract_sha256="not-the-real-hash",
    )
    (tmp_path / "artifacts/model").mkdir(parents=True)
    joblib.dump(artifact, tmp_path / "artifacts/model/risk_model.joblib")
    with pytest.raises(ModelContractError, match="different feature"):
        RiskModel.load(tmp_path)


def test_registry_reports_the_development_stage_not_a_final_model():
    registry = ArtifactRegistry.load(ROOT)
    summary = registry.system_summary()
    assert summary["model_status"] == READY
    assert summary["policy_mode"] == "model_and_rules"
    assert summary["model_stage"] == "development_frozen_candidate"
    assert summary["evaluation_status"] == "development_validation_only"
    assert summary["feature_contract_sha256"] == MODEL_FEATURES_SHA256


# --- policy interaction -----------------------------------------------------


def _policy() -> RiskPolicy:
    from card_testing_sentinel.common.config import load_config

    return RiskPolicy(load_config(ROOT / "configs/policy.yaml")["policy"])


def _snapshot(**overrides) -> dict:
    return {**dict.fromkeys(MODEL_FEATURES, 0.0), **overrides}


def test_the_score_alone_drives_the_review_band():
    policy = _policy()
    quiet = _snapshot()
    assert (
        policy.decide(snapshot=quiet, risk_score=0.01, timestamp=START).action
        == "allow"
    )
    review = policy.decide(
        snapshot=quiet, risk_score=policy.review_threshold, timestamp=START
    )
    assert review.action == "review"
    assert "elevated_model_risk" in review.reason_codes


def test_a_high_score_alone_does_not_block_without_evidence():
    """Phase 5 makes the deterministic layer *evidence* rather than a second
    detector: a block needs corroborating merchant-visible behaviour, so a
    high score on an otherwise silent device only reviews."""
    policy = _policy()
    if policy.family == "threshold":
        pytest.skip("the selected policy family has no evidence gate")
    silent = _snapshot()
    decision = policy.decide(snapshot=silent, risk_score=1.0, timestamp=START)
    assert decision.action == "review"

    corroborated = _snapshot(
        recent_failures_24h=4, decline_streak=3, sessions_24h=4, requests_24h=8
    )
    blocked = policy.decide(snapshot=corroborated, risk_score=1.0, timestamp=START)
    assert blocked.action == "block"
    assert blocked.block_expires_at == START + policy.block_ttl
    assert "elevated_model_risk" in blocked.reason_codes


def test_rules_no_longer_escalate_on_their_own_in_normal_mode():
    """Validation showed the rule layer added no detection beyond the model,
    so it no longer escalates independently. It survives as evidence, audit
    and the degraded failover -- and that change is asserted here."""
    policy = _policy()
    noisy = _snapshot(requests_60s=9, requests_5m=9, sessions_24h=4, requests_24h=9)
    decision = policy.decide(snapshot=noisy, risk_score=0.0, timestamp=START)
    assert decision.action == "allow"
    assert decision.rule_score >= policy.degraded_review_rule_score


def test_the_degraded_path_is_labelled_and_uses_rule_thresholds_only():
    policy = _policy()
    quiet = policy.decide(snapshot=_snapshot(), risk_score=None, timestamp=START)
    assert quiet.risk_score is None
    assert quiet.reason_codes == ("degraded_rules_only",)
    assert quiet.action == "allow"

    noisy = _snapshot(requests_60s=9, requests_5m=9, sessions_24h=4, requests_24h=9)
    escalated = policy.decide(snapshot=noisy, risk_score=None, timestamp=START)
    assert escalated.action in {"review", "block"}
    assert "degraded_rules_only" in escalated.reason_codes


def test_the_service_returns_a_real_score_and_a_rule_score(registry):
    service = RiskService(
        registry,
        InMemoryStateRepository(),
        IdentifierProtector.from_secret("model-runtime-secret-0123456789"),
    )
    response = asyncio.run(
        service.precheck(PrecheckRequest(**precheck_payload(1, base=START)))
    )
    assert response.model_status == READY
    assert response.decision_basis == "model_and_rules"
    assert response.risk_score is not None and 0.0 <= response.risk_score <= 1.0
    assert isinstance(response.rule_score, int)


def test_the_current_outcome_still_cannot_influence_its_own_score(registry):
    """The causal guarantee must survive the model becoming real."""
    service = RiskService(
        registry,
        InMemoryStateRepository(),
        IdentifierProtector.from_secret("model-runtime-secret-0123456789"),
    )
    first = asyncio.run(
        service.precheck(PrecheckRequest(**precheck_payload(1, base=START)))
    )
    asyncio.run(
        service.outcome(
            OutcomeRequest(
                event_id="o1",
                request_id="request-1",
                device_id="device-demo",
                session_id="session-demo",
                timestamp=START + timedelta(seconds=11),
                event_sequence=2,
                authorization_result="declined",
                failure_reason="do_not_honor",
            )
        )
    )
    replay = asyncio.run(
        service.precheck(PrecheckRequest(**precheck_payload(1, base=START)))
    )
    # the stored decision is returned verbatim; the later decline cannot
    # retroactively change the score that was already given
    assert replay.idempotent_replay is True
    assert replay.risk_score == first.risk_score

    later = asyncio.run(
        service.precheck(PrecheckRequest(**precheck_payload(3, base=START)))
    )
    assert later.risk_score != first.risk_score
