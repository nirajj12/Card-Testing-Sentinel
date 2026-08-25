import pandas as pd
import pytest

from card_testing_sentinel.common.exceptions import PolicyEvaluationError
from card_testing_sentinel.policy.engine import decide_action, replay_policy


def test_combined_boundaries_and_reason_codes():
    thresholds = {
        "ml_review_threshold": 0.7,
        "ml_block_threshold": 0.9,
        "rule_review_score": 3,
        "combined_block_rule_score": 2,
    }
    assert decide_action("combined", 0.9, 0, thresholds) == (
        "block_next_attempt",
        "model_block_threshold",
    )
    assert decide_action("combined", 0.7, 2, thresholds) == (
        "block_next_attempt",
        "model_rule_joint_block",
    )
    assert decide_action("combined", 0.7, 0, thresholds) == (
        "review",
        "model_review_threshold",
    )
    assert decide_action("combined", 0.1, 3, thresholds) == (
        "review",
        "rule_review_threshold",
    )


def test_replay_marks_rows_after_terminal_block():
    events = pd.DataFrame(
        {
            "device_id": ["d", "d"],
            "timestamp": pd.to_datetime(["2026-01-01", "2026-01-02"]),
            "event_sequence": [1, 2],
            "risk_score": [0.9, 0.1],
            "rule_score": [0, 0],
        }
    )
    replay = replay_policy(
        events, "ml_only", {"ml_review_threshold": 0.7, "ml_block_threshold": 0.9}
    )
    assert replay["action"].tolist() == ["block_next_attempt", "potentially_prevented"]
    assert replay["authorization_position"].tolist() == [1, 2]


def test_threshold_order_is_enforced():
    with pytest.raises(PolicyEvaluationError):
        decide_action("unknown", 0.0, 0, {})
