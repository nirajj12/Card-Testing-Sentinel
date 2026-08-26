"""Unit tests for the allowlisted operations-evidence projection (Stage 4
backend preparation for the future fraud-operations panel)."""

from __future__ import annotations

import pytest

from card_testing_sentinel.services.operations_projection import (
    SAFE_EVIDENCE_FEATURES,
    build_projection,
    risk_band,
    safe_evidence,
)


@pytest.mark.parametrize(
    ("score", "expected_band"),
    [
        (0.0, "low"),
        (0.24, "low"),
        (0.25, "elevated"),
        (0.49, "elevated"),
        (0.5, "high"),
        (0.74, "high"),
        (0.75, "very_high"),
        (1.0, "very_high"),
    ],
)
def test_risk_band_uses_fixed_generic_buckets(score, expected_band):
    assert risk_band(score) == expected_band


def test_risk_bands_are_independent_of_any_private_policy_threshold():
    """The bucket boundaries are hardcoded constants in this module, not
    read from configs/policy.yaml or the loaded candidate dict -- this test
    just documents that risk_band takes no policy input at all."""
    import inspect

    signature = inspect.signature(risk_band)
    assert list(signature.parameters) == ["risk_score"]


def test_safe_evidence_selects_only_the_allowlist():
    snapshot = {
        "prior_attempts_24h": 3,
        "distinct_cards_24h": 2,
        "prior_decline_streak": 1,
        "sessions_24h": 1,
        "ip_changes_24h": 0,
        "prior_successful_checkouts": 4,
        # everything below must never appear in the result
        "device_age_seconds": 12345,
        "amount_delta_from_previous": 5.0,
        "campaign_active": True,
        "current_amount": 999.0,
    }
    result = safe_evidence(snapshot)
    assert set(result) == set(SAFE_EVIDENCE_FEATURES)
    assert result["prior_attempts_24h"] == 3
    assert "device_age_seconds" not in result
    assert "amount_delta_from_previous" not in result


def test_safe_evidence_allowlist_matches_stage4_bullet_list_exactly():
    assert SAFE_EVIDENCE_FEATURES == (
        "prior_attempts_24h",
        "distinct_cards_24h",
        "prior_decline_streak",
        "sessions_24h",
        "ip_changes_24h",
        "prior_successful_checkouts",
    )


def test_safe_evidence_returns_empty_dict_for_missing_or_empty_snapshot():
    assert safe_evidence(None) == {}
    assert safe_evidence({}) == {}


def test_safe_evidence_never_fabricates_a_missing_feature():
    partial = {"prior_attempts_24h": 1}
    result = safe_evidence(partial)
    assert result == {"prior_attempts_24h": 1}


def test_build_projection_contains_only_allowlisted_keys():
    projection = build_projection(
        decision="review",
        risk_score=0.6,
        rule_score=2,
        reason_codes=["persistent_high_model_risk"],
        state_version=5,
        latency_ms=1.23,
        idempotent_replay=False,
        authorization="sent",
        outcome_status="declined",
        checkout_status=None,
        evidence={"prior_attempts_24h": 2},
        protected_reference="hmac_device_ab12",
    )
    assert set(projection) == {
        "decision",
        "risk_score",
        "risk_band",
        "risk_score_label",
        "rule_score",
        "reason_codes",
        "state_version",
        "latency_ms",
        "idempotent_replay",
        "authorization",
        "outcome_status",
        "checkout_status",
        "evidence",
        "protected_reference",
    }
    assert projection["risk_band"] == "high"
    assert "44" not in str(projection)


def test_build_projection_rejects_an_invalid_authorization_value():
    with pytest.raises(ValueError):
        build_projection(
            decision="allow",
            risk_score=0.1,
            rule_score=0,
            reason_codes=[],
            state_version=1,
            latency_ms=0.5,
            idempotent_replay=False,
            authorization="maybe",
            outcome_status=None,
            checkout_status=None,
            evidence={},
            protected_reference=None,
        )
