from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from card_testing_sentinel.v2.evaluation.sequential import replay_policy
from card_testing_sentinel.v2.modeling.features import MODEL_FEATURE_COLUMNS
from card_testing_sentinel.v2.modeling.folds import (
    assert_fold_integrity,
    make_device_folds,
)
from card_testing_sentinel.v2.modeling.weights import (
    balanced_device_training_weights,
    device_evaluation_weights,
)
from card_testing_sentinel.v2.policy.selection import enumerate_policy_grid


class ConstantArtifact:
    def __init__(self, probability: float):
        self.probability = probability

    def predict_raw_proba(self, frame):
        return np.full(len(frame), self.probability)

    def predict_proba(self, frame):
        return np.full(len(frame), self.probability)


def test_device_weights_and_balanced_training_mass():
    frame = pd.DataFrame(
        {
            "device_id": ["a", "a", "b", "c", "c", "c"],
            "label": [0, 0, 0, 1, 1, 1],
            "scenario_tag": [
                "normal",
                "normal",
                "normal",
                "attack",
                "attack",
                "attack",
            ],
        }
    )
    evaluation = device_evaluation_weights(frame)
    totals = pd.Series(evaluation).groupby(frame.device_id).sum()
    assert np.allclose(totals, 1.0)
    training = balanced_device_training_weights(frame)
    assert np.isclose(training[frame.label.eq(0)].sum(), 0.5)
    assert np.isclose(training[frame.label.eq(1)].sum(), 0.5)


def test_folds_are_deterministic_grouped_and_validation_free():
    training = pd.DataFrame(
        {
            "device_id": [f"d{index}" for index in range(20)],
            "scenario_tag": ["normal"] * 10 + ["attack"] * 10,
            "split": ["train"] * 20,
        }
    )
    first = make_device_folds(training)
    second = make_device_folds(training.sample(frac=1, random_state=4))
    pd.testing.assert_frame_equal(first, second)
    assert_fold_integrity(first, set(training.device_id), {"validation-device"})
    with pytest.raises(ValueError, match="validation device"):
        assert_fold_integrity(first, set(training.device_id), {"d1"})


def test_policy_grid_is_complete_deterministic_and_strict():
    config = {
        "families": {
            "rules_only": {"review_scores": [2, 3, 4], "block_scores": [4, 5, 6]},
            "ml_only": {
                "review_thresholds": [0.15, 0.25, 0.35, 0.45, 0.55],
                "block_thresholds": [0.6, 0.7, 0.8, 0.9],
            },
            "combined": {
                "review_thresholds": [0.25, 0.4],
                "block_thresholds": [0.7, 0.85],
                "review_scores": [2, 3],
                "block_support_scores": [2, 3],
            },
        }
    }
    candidates = enumerate_policy_grid(config)
    assert candidates == enumerate_policy_grid(config)
    assert len(candidates) == 32
    for candidate in candidates:
        if "review_threshold" in candidate:
            assert candidate["review_threshold"] < candidate["block_threshold"]
        if candidate["family"] == "rules_only":
            assert candidate["review_score"] < candidate["block_score"]
        if candidate["family"] == "combined":
            assert candidate["review_score"] < candidate["block_support_score"]


def _request(sequence: int, request_id: str, timestamp: datetime) -> dict:
    return {
        "event_id": f"event-{sequence}",
        "request_id": request_id,
        "event_sequence": sequence,
        "timestamp": timestamp.isoformat(),
        "event_type": "authorization_request",
        "device_id": "device-1",
        "session_id": "session-1",
        "ip_fingerprint": "ip-1",
        "card_fingerprint": f"card-{sequence}",
        "card_bin": "411111",
        "amount": 1.0,
        "currency": "INR",
        "campaign_active": False,
        "label": 1,
    }


def _outcome(sequence: int, request_id: str, timestamp: datetime) -> dict:
    return {
        "event_id": f"event-{sequence}",
        "request_id": request_id,
        "event_sequence": sequence,
        "timestamp": timestamp.isoformat(),
        "event_type": "authorization_outcome",
        "device_id": "device-1",
        "session_id": "session-1",
        "authorization_result": "approved",
        "label": 1,
    }


def _contract():
    return pd.DataFrame(
        [
            {
                "device_id": "device-1",
                "population": "attack",
                "attack_subtype": "patient",
                "scenario_tag": "attack_patient",
                "label": 1,
            }
        ]
    )


def test_current_block_scores_once_suppresses_outcome_and_later_state():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    raw = pd.DataFrame(
        [
            _request(1, "request-1", start),
            _outcome(2, "request-1", start + timedelta(seconds=1)),
            _request(3, "request-2", start + timedelta(seconds=2)),
            _outcome(4, "request-2", start + timedelta(seconds=3)),
        ]
    )
    policy = {"family": "ml_only", "review_threshold": 0.2, "block_threshold": 0.8}
    decisions, devices = replay_policy(raw, ConstantArtifact(0.99), policy, _contract())
    assert list(decisions.action) == [
        "block_current_attempt",
        "counterfactual_after_block",
    ]
    assert decisions.counterfactual_after_block.sum() == 1
    assert devices.loc[0, "first_block_request"] == 1
    assert devices.loc[0, "authorizations_processed_before_first_action"] == 0
    assert devices.loc[0, "potentially_preventable_later_requests_upper_bound"] == 1


def test_review_processes_recorded_outcome_under_frozen_assumption():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    raw = pd.DataFrame(
        [
            _request(1, "request-1", start),
            _outcome(2, "request-1", start + timedelta(seconds=1)),
            _request(3, "request-2", start + timedelta(seconds=2)),
            _outcome(4, "request-2", start + timedelta(seconds=3)),
        ]
    )
    policy = {"family": "ml_only", "review_threshold": 0.4, "block_threshold": 0.8}
    decisions, _ = replay_policy(raw, ConstantArtifact(0.5), policy, _contract())
    assert list(decisions.action) == ["review", "review"]
    assert list(decisions.processed_authorizations_before_action) == [0, 1]


def test_model_contract_contains_only_explicit_numeric_features():
    forbidden = {
        "device_id",
        "session_id",
        "label",
        "attack_subtype",
        "scenario_tag",
        "timestamp",
    }
    assert len(MODEL_FEATURE_COLUMNS) == 37
    assert not forbidden & set(MODEL_FEATURE_COLUMNS)
