"""Deterministic post-authorization policy decisions and replay."""

from typing import Any

import pandas as pd

from card_testing_sentinel.common.exceptions import PolicyEvaluationError

ACTIONS = {"allow", "review", "block_next_attempt"}


def decide_action(
    method: str, risk_score: float, rule_score: int, thresholds: dict[str, Any]
) -> tuple[str, str]:
    """Return one action and stable reason code for a processed authorization."""
    if method == "rules_only":
        if rule_score >= thresholds["rule_block_score"]:
            return "block_next_attempt", "rule_block_threshold"
        if rule_score >= thresholds["rule_review_score"]:
            return "review", "rule_review_threshold"
    elif method == "ml_only":
        if risk_score >= thresholds["ml_block_threshold"]:
            return "block_next_attempt", "model_block_threshold"
        if risk_score >= thresholds["ml_review_threshold"]:
            return "review", "model_review_threshold"
    elif method == "combined":
        if risk_score >= thresholds["ml_block_threshold"]:
            return "block_next_attempt", "model_block_threshold"
        if (
            risk_score >= thresholds["ml_review_threshold"]
            and rule_score >= thresholds["combined_block_rule_score"]
        ):
            return "block_next_attempt", "model_rule_joint_block"
        if risk_score >= thresholds["ml_review_threshold"]:
            return "review", "model_review_threshold"
        if rule_score >= thresholds["rule_review_score"]:
            return "review", "rule_review_threshold"
    else:
        raise PolicyEvaluationError(f"unknown policy method: {method}")
    return "allow", ""


def validate_threshold_order(method: str, thresholds: dict[str, Any]) -> None:
    if (
        method == "rules_only"
        and thresholds["rule_block_score"] < thresholds["rule_review_score"]
    ):
        raise PolicyEvaluationError(
            "rule block threshold must be at least review threshold"
        )
    if (
        method in {"ml_only", "combined"}
        and thresholds["ml_block_threshold"] < thresholds["ml_review_threshold"]
    ):
        raise PolicyEvaluationError(
            "ML block threshold must be at least review threshold"
        )


def replay_policy(
    events: pd.DataFrame, method: str, thresholds: dict[str, Any]
) -> pd.DataFrame:
    """Replay ordered authorizations; rows after a terminal block are estimates only."""
    validate_threshold_order(method, thresholds)
    ordered = (
        events.sort_values(
            ["device_id", "timestamp", "event_sequence"], kind="mergesort"
        )
        .reset_index(drop=True)
        .copy()
    )
    output = []
    for _, device_events in ordered.groupby("device_id", sort=False, observed=True):
        blocked = False
        reviewed = False
        for position, (_, row) in enumerate(device_events.iterrows(), start=1):
            record = row.to_dict()
            record["authorization_position"] = position
            if blocked:
                record.update(
                    action="potentially_prevented",
                    policy_reason_code="after_terminal_block",
                    is_first_review=False,
                    is_first_block=False,
                    potentially_prevented=True,
                )
            else:
                action, reason = decide_action(
                    method, float(row["risk_score"]), int(row["rule_score"]), thresholds
                )
                first_review = action == "review" and not reviewed
                first_block = action == "block_next_attempt"
                record.update(
                    action=action,
                    policy_reason_code=reason,
                    is_first_review=first_review,
                    is_first_block=first_block,
                    potentially_prevented=False,
                )
                reviewed = reviewed or action == "review"
                blocked = blocked or first_block
            output.append(record)
    return pd.DataFrame(output)
