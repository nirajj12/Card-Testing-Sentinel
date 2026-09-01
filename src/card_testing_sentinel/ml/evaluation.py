"""Validation evaluation: baselines, device-level behaviour, ablations.

Every approach below is scored on the *same* validation population so the
comparison is honest. The question this file exists to answer is whether the
model adds anything over a request counter and the existing deterministic
rules -- not to make the model look good.

A note on precision: this benchmark deliberately enriches attackers, so any
precision figure here is `benchmark_precision` and is reported as such.
Recall, FPR and the per-scenario breakdowns are far less sensitive to that
sampling choice and are the numbers that should carry the argument.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from card_testing_sentinel.features.specification import MODEL_FEATURES
from card_testing_sentinel.ml.metrics import (
    balanced_training_weights,
    device_weights,
    probability_metrics,
)
from card_testing_sentinel.policy.rules import evaluate_rules

#: Feature groups for the ablation study.
VELOCITY_FEATURES = (
    "requests_10s",
    "requests_60s",
    "requests_5m",
    "requests_24h",
    "requests_per_ip_5m",
    "devices_per_ip_24h",
    "seconds_since_last_request",
    "ip_changes_24h",
    "device_age_seconds",
    "is_new_device",
    "session_age_seconds",
    "sessions_24h",
    "ip_rotation_ratio_24h",
)
HISTORY_FEATURES = (
    "prior_payments_24h",
    "recent_failures_24h",
    "failure_ratio_24h",
    "decline_streak",
    "successful_checkouts",
    "seconds_since_last_payment",
    "seconds_since_last_success",
    "retry_after_decline_ratio_24h",
)
CARD_HISTORY_FEATURES = (
    "distinct_card_last4_7d",
    "distinct_card_networks_7d",
    "card_change_after_decline_7d",
)


def rule_scores(frame: pd.DataFrame) -> np.ndarray:
    """Run the deterministic rule layer over the feature table, so the
    rules-only baseline is the *actual* runtime rules, not a reimplementation."""
    return np.array(
        [
            evaluate_rules(row)[0]
            for row in frame.loc[:, list(MODEL_FEATURES)].to_dict("records")
        ],
        dtype=float,
    )


# --------------------------------------------------------------------------
# device-level behaviour
# --------------------------------------------------------------------------


def device_outcomes(frame: pd.DataFrame, flagged: np.ndarray) -> pd.DataFrame:
    """Collapse attempt-level flags to one row per device.

    Card testing is a sequence, so "did we ever act on this device, and on
    which attempt" is the question that matters operationally.
    """
    working = frame.loc[
        :,
        ["device_id", "label", "scenario", "population", "merchant_kind", "timestamp"],
    ].copy()
    working["flagged"] = np.asarray(flagged, dtype=bool)
    working = working.sort_values(["device_id", "timestamp"], kind="mergesort")
    working["attempt"] = working.groupby("device_id").cumcount() + 1

    first = (
        working.loc[working.flagged]
        .groupby("device_id")
        .attempt.min()
        .rename("first_detection_attempt")
    )
    summary = working.groupby("device_id").agg(
        label=("label", "first"),
        scenario=("scenario", "first"),
        population=("population", "first"),
        merchant_kind=("merchant_kind", "first"),
        attempts=("attempt", "max"),
        ever_flagged=("flagged", "any"),
    )
    return summary.join(first)


def device_summary(devices: pd.DataFrame) -> dict:
    attack = devices.loc[devices.label.eq(1)]
    legitimate = devices.loc[devices.label.eq(0)]
    detected = attack.loc[attack.ever_flagged]
    return {
        "attack_devices": int(len(attack)),
        "attack_detected": int(attack.ever_flagged.sum()),
        "attack_never_detected": int((~attack.ever_flagged).sum()),
        "attack_device_recall": round(float(attack.ever_flagged.mean()), 4)
        if len(attack)
        else 0.0,
        "legitimate_devices": int(len(legitimate)),
        "legitimate_flagged": int(legitimate.ever_flagged.sum()),
        "legitimate_device_fpr": round(float(legitimate.ever_flagged.mean()), 4)
        if len(legitimate)
        else 0.0,
        "median_first_detection_attempt": (
            float(detected.first_detection_attempt.median()) if len(detected) else None
        ),
        "p90_first_detection_attempt": (
            float(detected.first_detection_attempt.quantile(0.90))
            if len(detected)
            else None
        ),
    }


def attempt_summary(frame: pd.DataFrame, flagged: np.ndarray) -> dict:
    labels = frame.label.to_numpy(dtype=int)
    flagged = np.asarray(flagged, dtype=bool)
    true_positive = int(((labels == 1) & flagged).sum())
    false_positive = int(((labels == 0) & flagged).sum())
    false_negative = int(((labels == 1) & ~flagged).sum())
    true_negative = int(((labels == 0) & ~flagged).sum())
    return {
        "attempt_recall": round(
            true_positive / max(true_positive + false_negative, 1), 4
        ),
        "attempt_fpr": round(
            false_positive / max(false_positive + true_negative, 1), 4
        ),
        "attempt_specificity": round(
            true_negative / max(false_positive + true_negative, 1), 4
        ),
        # benchmark-prevalence dependent -- see the module docstring
        "benchmark_precision": round(
            true_positive / max(true_positive + false_positive, 1), 4
        ),
        "flag_rate": round(float(flagged.mean()), 4),
    }


def approach_row(name: str, family: str, frame: pd.DataFrame, flagged) -> dict:
    devices = device_outcomes(frame, flagged)
    return {
        "approach": name,
        "family": family,
        **attempt_summary(frame, flagged),
        **device_summary(devices),
    }


# --------------------------------------------------------------------------
# baselines
# --------------------------------------------------------------------------


def baseline_comparison(
    frame: pd.DataFrame,
    risk: np.ndarray,
    rules: np.ndarray,
    config: dict,
) -> pd.DataFrame:
    """Every approach on the same validation rows."""
    rows = [
        # Baseline 0: no Sentinel at all. Zero friction, zero detection.
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
    # Combined: the model flags, OR the deterministic rules corroborate on
    # their own. Provisional -- the real operating point is chosen next phase.
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


def threshold_sweep(frame: pd.DataFrame, risk: np.ndarray) -> pd.DataFrame:
    rows = []
    for threshold in np.round(np.arange(0.05, 1.0, 0.05), 2):
        rows.append(
            {
                "threshold": float(threshold),
                **attempt_summary(frame, risk >= threshold),
                **device_summary(device_outcomes(frame, risk >= threshold)),
            }
        )
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# per-group breakdowns
# --------------------------------------------------------------------------


def scenario_metrics(frame: pd.DataFrame, flagged: np.ndarray) -> pd.DataFrame:
    devices = device_outcomes(frame, flagged)
    requests = frame.groupby("scenario").size().rename("requests")
    grouped = devices.groupby("scenario").agg(
        population=("population", "first"),
        devices=("label", "size"),
        label=("label", "first"),
        flagged_devices=("ever_flagged", "sum"),
        median_detection_attempt=("first_detection_attempt", "median"),
        p90_detection_attempt=("first_detection_attempt", lambda s: s.quantile(0.90)),
    )
    grouped = grouped.join(requests)
    grouped["never_flagged_devices"] = grouped.devices - grouped.flagged_devices
    # For attack scenarios this column is recall; for legitimate scenarios it
    # is the false-positive rate. Named neutrally, interpreted by population.
    grouped["flagged_device_rate"] = (grouped.flagged_devices / grouped.devices).round(
        4
    )
    grouped["recall_or_fpr"] = np.where(
        grouped.label.eq(1), "recall", "false_positive_rate"
    )
    return grouped.drop(columns="label").sort_values(
        ["population", "flagged_device_rate"], ascending=[True, False]
    )


def merchant_metrics(frame: pd.DataFrame, flagged: np.ndarray) -> pd.DataFrame:
    devices = device_outcomes(frame, flagged)
    requests = frame.groupby("merchant_kind").size().rename("requests")
    rows = []
    for kind, group in devices.groupby("merchant_kind"):
        attack = group.loc[group.label.eq(1)]
        legitimate = group.loc[group.label.eq(0)]
        rows.append(
            {
                "merchant_kind": kind,
                "devices": int(len(group)),
                "attack_devices": int(len(attack)),
                "legitimate_devices": int(len(legitimate)),
                "attack_recall": round(float(attack.ever_flagged.mean()), 4)
                if len(attack)
                else None,
                "legitimate_fpr": round(float(legitimate.ever_flagged.mean()), 4)
                if len(legitimate)
                else None,
            }
        )
    return pd.DataFrame(rows).merge(
        requests.reset_index(), on="merchant_kind", how="left"
    )


def risk_by_scenario(frame: pd.DataFrame, risk: np.ndarray) -> pd.DataFrame:
    working = frame[["scenario", "population"]].copy()
    working["risk"] = risk
    return (
        working.groupby(["population", "scenario"])
        .risk.agg(median="median", p90=lambda s: s.quantile(0.90), max="max")
        .round(4)
        .reset_index()
    )


# --------------------------------------------------------------------------
# ablations
# --------------------------------------------------------------------------


def run_ablation(
    training: pd.DataFrame,
    validation: pd.DataFrame,
    candidate,
    seed: int,
    feature_sets: dict[str, tuple[str, ...]],
    reference_flag_rate: float,
) -> pd.DataFrame:
    """Refit the selected candidate on feature subsets.

    This measures where the model's value comes from -- especially whether it
    survives losing the three weak card-history features. The production
    contract is NOT changed on the strength of this; it is evidence only.

    Ablation models are refitted raw (no calibrator), so a fixed score
    threshold would mean something different for each one. Instead every
    feature set is thresholded at the same *flag rate* as the reference
    model, which makes recall and FPR directly comparable across rows.
    PR-AUC and ROC-AUC are threshold-free and need no such adjustment.
    """
    rows = []
    weights = device_weights(validation)
    for name, features in feature_sets.items():
        columns = list(features)
        model = _fit_subset(training, columns, candidate, seed)
        scores = _predict_subset(model, validation, columns, candidate)
        threshold = float(np.quantile(scores, 1.0 - reference_flag_rate))
        devices = device_outcomes(validation, scores >= threshold)
        summary = device_summary(devices)
        rows.append(
            {
                "feature_set": name,
                "features": len(columns),
                **{
                    key: round(value, 4)
                    for key, value in probability_metrics(
                        validation.label, scores, weights
                    ).items()
                },
                "matched_flag_rate": round(reference_flag_rate, 4),
                "matched_threshold": round(threshold, 4),
                "attack_device_recall": summary["attack_device_recall"],
                "legitimate_device_fpr": summary["legitimate_device_fpr"],
            }
        )
    return pd.DataFrame(rows)


def _fit_subset(training: pd.DataFrame, columns: list[str], candidate, seed: int):
    from sklearn.compose import ColumnTransformer
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    weights = balanced_training_weights(training)
    if candidate.family == "logistic_regression":
        numeric = Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler()),
            ]
        )
        model = Pipeline(
            [
                (
                    "preprocessing",
                    ColumnTransformer(
                        [("numeric", numeric, columns)], remainder="drop"
                    ),
                ),
                (
                    "classifier",
                    LogisticRegression(random_state=seed, **candidate.parameters),
                ),
            ]
        )
        model.fit(
            training.loc[:, columns], training.label, classifier__sample_weight=weights
        )
        return model
    model = HistGradientBoostingClassifier(random_state=seed, **candidate.parameters)
    model.fit(
        training.loc[:, columns].to_numpy(dtype=float),
        training.label,
        sample_weight=weights,
    )
    return model


def _predict_subset(model, frame: pd.DataFrame, columns: list[str], candidate):
    values = (
        frame.loc[:, columns]
        if candidate.family == "logistic_regression"
        else frame.loc[:, columns].to_numpy(dtype=float)
    )
    return np.asarray(model.predict_proba(values)[:, 1], dtype=float)
