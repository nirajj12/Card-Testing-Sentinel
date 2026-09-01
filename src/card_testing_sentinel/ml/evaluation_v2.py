"""Model v2 development-validation evaluation.

Scored once, after the candidate, its hyperparameters and its calibration
were frozen from train cross-validation. Nothing here is tuned.

Every device-level helper is imported from `ml/evaluation.py` -- the same
functions that produced the v1 and Blind v1.1 numbers -- so a v1-to-v2
comparison cannot be an artifact of a redefined metric.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from card_testing_sentinel.ml.evaluation import (
    approach_row,
    attempt_summary,
    device_outcomes,
    device_summary,
)
from card_testing_sentinel.ml.metrics import device_weights, probability_metrics
from card_testing_sentinel.policy.rules import evaluate_rules


def rule_scores_v2(frame: pd.DataFrame) -> np.ndarray:
    """The runtime rule layer over v2 rows.

    Every feature the rules read survives into contract v2, so this is the
    actual deterministic rule score, not a reimplementation.
    """
    return np.array(
        [evaluate_rules(row)[0] for row in frame.to_dict("records")], dtype=float
    )


def threshold_table(frame: pd.DataFrame, risk: np.ndarray, thresholds) -> pd.DataFrame:
    """Operational behaviour at fixed score cuts.

    Reported so the policy phase has evidence to choose from. No threshold is
    selected here.
    """
    rows = []
    for threshold in thresholds:
        flagged = risk >= float(threshold)
        devices = device_outcomes(frame, flagged)
        summary = device_summary(devices)
        attempts = attempt_summary(frame, flagged)
        rows.append(
            {
                "threshold": float(threshold),
                "attack_device_recall": summary["attack_device_recall"],
                "legitimate_device_fpr": summary["legitimate_device_fpr"],
                "attack_devices_detected": summary["attack_detected"],
                "attack_never_detected": summary["attack_never_detected"],
                "legitimate_devices_flagged": summary["legitimate_flagged"],
                # prevalence-conditional: this benchmark enriches attackers
                "benchmark_precision": attempts["benchmark_precision"],
                "attempt_flag_rate": attempts["flag_rate"],
                "median_first_detection_attempt": summary[
                    "median_first_detection_attempt"
                ],
            }
        )
    return pd.DataFrame(rows)


def baseline_table(
    frame: pd.DataFrame, risk: np.ndarray, rules: np.ndarray, config: dict
) -> pd.DataFrame:
    """Every v1 baseline at its exact v1 threshold, plus the two new counters.

    The new baselines exist so Model v2 cannot claim credit that belongs to
    the horizon or the customer key rather than to the model.
    """
    rows = [
        approach_row("no_sentinel", "baseline", frame, np.zeros(len(frame), dtype=bool))
    ]
    for threshold in config["request_count_thresholds"]:
        rows.append(
            approach_row(
                f"count_requests_5m_ge_{threshold}",
                "request_count",
                frame,
                frame.requests_5m.to_numpy(dtype=float) >= threshold,
            )
        )
    for threshold in config["request_count_24h_thresholds"]:
        rows.append(
            approach_row(
                f"count_requests_24h_ge_{threshold}",
                "request_count",
                frame,
                frame.requests_24h.to_numpy(dtype=float) >= threshold,
            )
        )
    for threshold in config["failures_7d_thresholds"]:
        rows.append(
            approach_row(
                f"failures_7d_ge_{threshold}",
                "long_horizon_count",
                frame,
                frame.failures_7d.to_numpy(dtype=float) >= threshold,
            )
        )
    for threshold in config["customer_devices_thresholds"]:
        rows.append(
            approach_row(
                f"customer_devices_7d_ge_{threshold}",
                "cross_device_count",
                frame,
                frame.customer_distinct_devices_7d.to_numpy(dtype=float) >= threshold,
            )
        )
    for threshold in config["rule_score_thresholds"]:
        rows.append(
            approach_row(
                f"rules_ge_{threshold}", "rules_only", frame, rules >= threshold
            )
        )
    for threshold in config["risk_thresholds"]:
        rows.append(
            approach_row(
                f"model_ge_{threshold}", "model_only", frame, risk >= threshold
            )
        )
    for risk_threshold in config["combined_risk_thresholds"]:
        for rule_threshold in config["combined_rule_thresholds"]:
            rows.append(
                approach_row(
                    f"model_ge_{risk_threshold}_or_rules_ge_{rule_threshold}",
                    "model_and_rules",
                    frame,
                    (risk >= risk_threshold) | (rules >= rule_threshold),
                )
            )
    return pd.DataFrame(rows)


def matched_fpr_comparison(
    baselines: pd.DataFrame, tolerance: float = 0.012
) -> pd.DataFrame:
    """For each non-model baseline, the model row at the closest FPR.

    ML value is claimed from recall at comparable friction, never from AUC.
    """
    model = baselines.loc[baselines.family.eq("model_only")]
    rows = []
    for _, baseline in baselines.loc[
        baselines.family.isin(
            ("request_count", "rules_only", "long_horizon_count", "cross_device_count")
        )
    ].iterrows():
        if baseline.legitimate_device_fpr <= 0:
            continue
        gaps = (model.legitimate_device_fpr - baseline.legitimate_device_fpr).abs()
        nearest = model.loc[gaps.idxmin()]
        if (
            abs(nearest.legitimate_device_fpr - baseline.legitimate_device_fpr)
            > tolerance
        ):
            continue
        rows.append(
            {
                "baseline": baseline.approach,
                "baseline_fpr": baseline.legitimate_device_fpr,
                "baseline_recall": baseline.attack_device_recall,
                "model": nearest.approach,
                "model_fpr": nearest.legitimate_device_fpr,
                "model_recall": nearest.attack_device_recall,
                "recall_gain": round(
                    float(nearest.attack_device_recall - baseline.attack_device_recall),
                    4,
                ),
            }
        )
    return pd.DataFrame(rows).sort_values("baseline_fpr")


def scenario_table(
    frame: pd.DataFrame, risk: np.ndarray, threshold: float
) -> pd.DataFrame:
    """Per-family device flag rate at one reporting threshold."""
    devices = device_outcomes(frame, risk >= threshold)
    grouped = devices.groupby("scenario").agg(
        population=("population", "first"),
        devices=("label", "size"),
        label=("label", "first"),
        flagged=("ever_flagged", "sum"),
        median_detection_attempt=("first_detection_attempt", "median"),
    )
    grouped["flag_rate"] = (grouped.flagged / grouped.devices).round(4)
    grouped["never_flagged"] = grouped.devices - grouped.flagged
    grouped["measure"] = np.where(
        grouped.label.eq(1), "attack_recall", "legitimate_false_positive_rate"
    )
    return grouped.drop(columns="label").sort_values(
        ["population", "flag_rate"], ascending=[True, False]
    )


def segment_table(frame: pd.DataFrame, risk: np.ndarray, thresholds) -> pd.DataFrame:
    """Model quality split by whether the request carried a customer identity.

    Model v2 must not work only because signed-in users are easier to judge.
    """
    working = frame.copy()
    working["risk"] = risk
    rows = []
    for present, group in working.groupby(working.customer_id_present.eq(1.0)):
        name = "customer_present" if present else "customer_absent"
        labels = group.label.to_numpy(dtype=int)
        if len(set(labels)) < 2:
            continue
        metrics = probability_metrics(
            labels, group.risk.to_numpy(dtype=float), device_weights(group)
        )
        entry = {
            "segment": name,
            "rows": int(len(group)),
            "devices": int(group.device_id.nunique()),
            "attack_share": round(float(labels.mean()), 4),
            "pr_auc": round(metrics["pr_auc"], 4),
            "roc_auc": round(metrics["roc_auc"], 4),
            "brier": round(metrics["brier"], 4),
            "ece": round(metrics["ece"], 4),
        }
        for threshold in thresholds:
            flagged = group.risk.to_numpy(dtype=float) >= float(threshold)
            summary = device_summary(device_outcomes(group, flagged))
            entry[f"recall@{threshold}"] = summary["attack_device_recall"]
            entry[f"fpr@{threshold}"] = summary["legitimate_device_fpr"]
        rows.append(entry)
    return pd.DataFrame(rows)
