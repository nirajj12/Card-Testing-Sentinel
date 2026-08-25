"""Validation-only policy selection under exact unique-device budgets."""

import math
from typing import Any

import numpy as np
import pandas as pd

from card_testing_sentinel.evaluation.sequential import (
    device_summary,
    sequential_metrics,
)
from card_testing_sentinel.policy.engine import replay_policy


def _budget_result(
    numerator: int, denominator: int, maximum_rate: float
) -> dict[str, Any]:
    allowed = math.floor(maximum_rate * denominator)
    return {
        "numerator_devices": int(numerator),
        "denominator_devices": int(denominator),
        "rate": numerator / denominator if denominator else None,
        "maximum_rate": maximum_rate,
        "maximum_allowed_devices": allowed,
        "rate_granularity": 1 / denominator if denominator else None,
        "passed": numerator <= allowed,
    }


def budget_checks(
    summary: pd.DataFrame, config: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    legitimate = summary.loc[summary["label"].eq(0)]
    checks = {
        "legitimate_review_or_higher": _budget_result(
            int(legitimate["ever_review_or_higher"].sum()),
            len(legitimate),
            float(config["maximum_legitimate_device_review_or_higher_rate"]),
        ),
        "legitimate_block": _budget_result(
            int(legitimate["ever_blocked"].sum()),
            len(legitimate),
            float(config["maximum_legitimate_device_block_rate"]),
        ),
    }
    masks = {
        "flash_sale_block": legitimate["population"].eq("flash_sale"),
        "flash_hard_retry_block": legitimate["scenario_exposures"].str.contains(
            r"(?:^|\|)flash_hard_retry(?:\||$)", regex=True
        ),
        "normal_bad_luck_block": legitimate["scenario_exposures"].str.contains(
            r"(?:^|\|)normal_bad_luck(?:\||$)", regex=True
        ),
    }
    guardrails = config["subgroup_block_guardrails"]
    for check_name, mask in masks.items():
        group = check_name.removesuffix("_block")
        part = legitimate.loc[mask]
        checks[check_name] = _budget_result(
            int(part["ever_blocked"].sum()), len(part), float(guardrails[group])
        )
    return checks


def evaluate_policy(
    events: pd.DataFrame,
    method: str,
    thresholds: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    replay = replay_policy(events, method, thresholds)
    summary = device_summary(replay)
    metrics = sequential_metrics(
        summary, replay, list(config["detection_within_attempt_cutoffs"])
    )
    budgets = budget_checks(summary, config)
    feasible = (
        all(item["passed"] for item in budgets.values())
        and metrics["detected_attacker_devices"] > 0
    )
    return {
        "method": method,
        "thresholds": thresholds,
        "feasible": feasible,
        "budgets": budgets,
        "metrics": metrics,
        "replay": replay,
        "device_summary": summary,
    }


def _better_key(result: dict[str, Any]) -> tuple:
    metrics = result["metrics"]
    thresholds = result["thresholds"]
    median = metrics["detection_attempt_position"]["median"]
    hard = result["budgets"]["flash_hard_retry_block"]
    conservative = tuple(float(value) for _, value in sorted(thresholds.items()))
    return (
        metrics["attacker_block_coverage"]["rate"],
        -(median if median is not None else 1e9),
        -hard["numerator_devices"],
        -hard["rate"],
        conservative,
    )


def _ml_boundaries(scores: pd.Series, quantiles: list[float]) -> list[float]:
    values = scores.to_numpy(dtype=float)
    return sorted(
        {
            float(np.quantile(values, quantile, method="nearest"))
            for quantile in quantiles
        }
    )


def _fast_candidate(
    events: pd.DataFrame,
    method: str,
    thresholds: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate selection fields vectorially; full replay runs only for winners."""
    frame = events.sort_values(
        ["device_id", "timestamp", "event_sequence"], kind="mergesort"
    ).copy()
    frame["position"] = frame.groupby("device_id", sort=False).cumcount() + 1
    risk = frame["risk_score"]
    rule = frame["rule_score"]
    if method == "rules_only":
        block = rule.ge(thresholds["rule_block_score"])
        review = rule.ge(thresholds["rule_review_score"])
    elif method == "ml_only":
        block = risk.ge(thresholds["ml_block_threshold"])
        review = risk.ge(thresholds["ml_review_threshold"])
    else:
        block = risk.ge(thresholds["ml_block_threshold"]) | (
            risk.ge(thresholds["ml_review_threshold"])
            & rule.ge(thresholds["combined_block_rule_score"])
        )
        review = risk.ge(thresholds["ml_review_threshold"]) | rule.ge(
            thresholds["rule_review_score"]
        )
    first = frame.drop_duplicates("device_id").set_index("device_id")
    summary = first[["population", "attack_subtype", "true_label"]].rename(
        columns={"true_label": "label"}
    )
    summary["scenario_exposures"] = frame.groupby("device_id")["scenario_tag"].agg(
        lambda values: "|".join(sorted(values.dropna().astype(str).unique()))
    )
    summary["ever_blocked"] = block.groupby(frame["device_id"]).any()
    summary["ever_review_or_higher"] = (
        (block | review).groupby(frame["device_id"]).any()
    )
    summary["first_block_position"] = (
        frame["position"].where(block).groupby(frame["device_id"]).min()
    )
    summary.reset_index(inplace=True)
    budgets = budget_checks(summary, config)
    attackers = summary.loc[summary["label"].eq(1)]
    detected = attackers.loc[attackers["ever_blocked"]]
    detected_count = int(len(detected))
    metrics = {
        "detected_attacker_devices": detected_count,
        "attacker_block_coverage": {
            "rate": detected_count / len(attackers) if len(attackers) else None
        },
        "detection_attempt_position": {
            "median": float(detected["first_block_position"].median())
            if detected_count
            else None
        },
    }
    return {
        "method": method,
        "thresholds": thresholds,
        "feasible": all(item["passed"] for item in budgets.values())
        and detected_count > 0,
        "budgets": budgets,
        "metrics": metrics,
    }


def select_policies(events: pd.DataFrame, config: dict[str, Any]) -> dict[str, Any]:
    """Select best feasible rules, ML, combined, then overall champion."""
    rule_scores = sorted(
        int(value) for value in events["rule_score"].unique() if value > 0
    )
    ml_scores = _ml_boundaries(
        events["risk_score"], list(config["ml_threshold_quantiles"])
    )
    candidate_sets: dict[str, list[dict[str, Any]]] = {
        "rules_only": [],
        "ml_only": [],
        "combined": [],
    }
    for review in rule_scores:
        for block in [score for score in rule_scores if score >= review]:
            candidate_sets["rules_only"].append(
                {"rule_review_score": review, "rule_block_score": block}
            )
    for review in ml_scores:
        for block in [score for score in ml_scores if score >= review]:
            candidate_sets["ml_only"].append(
                {"ml_review_threshold": review, "ml_block_threshold": block}
            )
            for rule_review in rule_scores[-2:]:
                for joint in rule_scores:
                    candidate_sets["combined"].append(
                        {
                            "ml_review_threshold": review,
                            "ml_block_threshold": block,
                            "rule_review_score": rule_review,
                            "combined_block_rule_score": joint,
                        }
                    )
    best = {}
    evaluated_counts = {}
    for method, candidates in candidate_sets.items():
        feasible = []
        for thresholds in candidates:
            result = _fast_candidate(events, method, thresholds, config)
            if result["feasible"]:
                feasible.append(result)
        evaluated_counts[method] = {
            "evaluated": len(candidates),
            "feasible": len(feasible),
        }
        chosen = max(feasible, key=_better_key) if feasible else None
        best[method] = (
            evaluate_policy(events, method, chosen["thresholds"], config)
            if chosen
            else None
        )
    available = [value for value in best.values() if value is not None]
    if not available:
        return {"champion": None, "methods": best, "candidate_counts": evaluated_counts}
    simplicity = {"rules_only": 2, "ml_only": 1, "combined": 0}
    champion = max(
        available,
        key=lambda result: (
            *_better_key(result)[:-1],
            simplicity[result["method"]],
            _better_key(result)[-1],
        ),
    )
    return {
        "champion": champion["method"],
        "methods": best,
        "candidate_counts": evaluated_counts,
    }


def serializable_result(result: dict[str, Any] | None) -> dict[str, Any] | None:
    if result is None:
        return None
    return {
        key: value
        for key, value in result.items()
        if key not in {"replay", "device_summary"}
    }
