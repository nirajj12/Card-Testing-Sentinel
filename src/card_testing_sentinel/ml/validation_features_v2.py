"""Leakage gates and per-feature diagnostics for Feature Contract v2.

Phase 8 shipped Dataset v3 with its gates run against the v1 feature
projection, so the new customer and long-horizon features had never been
leakage-tested. This module does that testing on the features that will
actually train Model v2.

Every gate definition is the same one the earlier phases used -- imported or
mirrored exactly -- so a v1-to-v2 comparison cannot be an artifact of a
redefined check. Nothing here fits a production model: the only estimator is
the shuffled-label probe, which is a pipeline sanity check by construction.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import precision_recall_curve, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

from card_testing_sentinel.features.specification_v2 import (
    CUSTOMER_FEATURES,
    MODEL_FEATURES_V2,
    NEW_IN_V2,
)
from card_testing_sentinel.ml.validation import ValidationReport, _overlap_coefficient

#: Features whose distributions must genuinely overlap between populations.
#: The v1 set plus the new long-horizon and customer signals.
OVERLAP_FEATURES_V2 = (
    "requests_5m",
    "sessions_24h",
    "failure_ratio_24h",
    "ip_changes_24h",
    "current_amount",
    "low_amount_ratio_24h",
    "requests_7d",
    "failures_7d",
    "active_day_count_7d",
    "customer_distinct_devices_7d",
    "customer_failures_7d",
    "customer_successful_checkouts_30d",
)


def max_univariate_f1(values: np.ndarray, labels: np.ndarray) -> float:
    """Best F1 any single threshold on this one feature can reach.

    Checked in both polarities, because a feature that separates by being
    unusually LOW is just as much a shortcut.
    """
    best = 0.0
    for signed in (values, -values):
        precision, recall, _ = precision_recall_curve(labels, signed)
        f1 = (
            2
            * precision[:-1]
            * recall[:-1]
            / np.maximum(precision[:-1] + recall[:-1], 1e-12)
        )
        best = max(best, float(f1.max()) if f1.size else 0.0)
    return best


def check_contract(features: pd.DataFrame, report: ValidationReport) -> None:
    ordered = [name for name in features.columns if name in set(MODEL_FEATURES_V2)]
    report.require(
        tuple(ordered) == MODEL_FEATURES_V2,
        "feature columns are missing or out of contract order",
    )
    values = features.loc[:, list(MODEL_FEATURES_V2)].to_numpy(dtype=float)
    report.require(bool(np.isfinite(values).all()), "non-finite feature values")
    degenerate = [
        name for name in MODEL_FEATURES_V2 if features[name].nunique(dropna=False) <= 1
    ]
    report.require(not degenerate, f"features with no variation at all: {degenerate}")
    report.summary["contract"] = {
        "feature_count": len(MODEL_FEATURES_V2),
        "rows": int(len(features)),
        "new_in_v2": list(NEW_IN_V2),
    }


def check_univariate_leakage(
    features: pd.DataFrame, report: ValidationReport, cap: float = 0.85
) -> None:
    labels = features.label.to_numpy(dtype=int)
    rows = []
    for name in MODEL_FEATURES_V2:
        best = max_univariate_f1(features[name].to_numpy(dtype=float), labels)
        rows.append({"feature": name, "max_f1": round(best, 4)})
        report.require(
            best <= cap,
            f"feature '{name}' alone reaches F1 {best:.3f} (> {cap}); do not "
            "train -- diagnose the generator or the feature semantics first",
        )
    table = pd.DataFrame(rows).sort_values("max_f1", ascending=False)
    report.summary["univariate_max_f1"] = table.head(12).to_dict("records")
    report.summary["univariate_max_f1_new_features"] = table.loc[
        table.feature.isin(NEW_IN_V2)
    ].to_dict("records")


def check_shuffled_labels(
    features: pd.DataFrame, report: ValidationReport, cap: float = 0.60, seed: int = 7
) -> None:
    """A probe trained on shuffled labels must land near random.

    This is the pipeline sanity check, not a model result: if it separates,
    something label-shaped reached the feature matrix.
    """
    rng = np.random.default_rng(seed)
    values = features.loc[:, list(MODEL_FEATURES_V2)].to_numpy(dtype=float)
    shuffled = rng.permutation(features.label.to_numpy(dtype=int))
    x_train, x_test, y_train, y_test = train_test_split(
        values, shuffled, test_size=0.3, random_state=seed, stratify=shuffled
    )
    scaler = StandardScaler().fit(x_train)
    probe = LogisticRegression(max_iter=200).fit(scaler.transform(x_train), y_train)
    auc = float(
        roc_auc_score(y_test, probe.predict_proba(scaler.transform(x_test))[:, 1])
    )
    report.summary["shuffled_label_roc_auc"] = round(auc, 4)
    report.require(
        auc <= cap,
        f"shuffled-label ROC-AUC {auc:.3f} > {cap}: the pipeline is leaking",
    )


def check_overlap(
    features: pd.DataFrame, report: ValidationReport, floor: float = 0.25
) -> None:
    legitimate = features.loc[features.label.eq(0)]
    attack = features.loc[features.label.eq(1)]
    overlaps = {}
    for name in OVERLAP_FEATURES_V2:
        coefficient = _overlap_coefficient(
            legitimate[name].to_numpy(dtype=float),
            attack[name].to_numpy(dtype=float),
        )
        overlaps[name] = round(coefficient, 4)
        report.require(
            coefficient >= floor,
            f"'{name}' distributions barely overlap ({coefficient:.2f} < {floor})",
        )
    report.summary["overlap_coefficient"] = overlaps


def check_customer_missingness(
    features: pd.DataFrame, report: ValidationReport, cap: float = 0.65
) -> None:
    """Absent customer identity must read as "unavailable", not "risky".

    Two things are checked. The presence flag must not separate the
    populations on its own, and the customer features must take their
    documented neutral value whenever the flag is 0 -- if a guest were
    assigned some other constant, that constant would itself be a signal.
    """
    labels = features.label.to_numpy(dtype=int)
    present = features.customer_id_present.to_numpy(dtype=float)
    single = max_univariate_f1(present, labels)
    report.require(
        single <= cap,
        f"customer_id_present alone reaches F1 {single:.3f} (> {cap})",
    )
    absent = features.loc[features.customer_id_present.eq(0.0)]
    for name in CUSTOMER_FEATURES:
        report.require(
            bool((absent[name] == 0.0).all()),
            f"'{name}' is not neutral for requests without a customer identity",
        )

    segments = {}
    for flag, group in features.groupby("customer_id_present"):
        name = "present" if flag == 1.0 else "absent"
        segments[name] = {
            "rows": int(len(group)),
            "attack_share": round(float(group.label.mean()), 4),
            "share_of_all_rows": round(float(len(group) / len(features)), 4),
        }
    gap = abs(
        segments.get("present", {}).get("attack_share", 0.0)
        - segments.get("absent", {}).get("attack_share", 0.0)
    )
    report.summary["customer_missingness"] = {
        "presence_single_feature_f1": round(single, 4),
        "segments": segments,
        "attack_share_gap": round(gap, 4),
    }


def feature_distributions(features: pd.DataFrame) -> pd.DataFrame:
    """Per-feature legitimate/attack shape, overlap, F1 and default rate."""
    labels = features.label.to_numpy(dtype=int)
    legitimate = features.loc[features.label.eq(0)]
    attack = features.loc[features.label.eq(1)]
    rows = []
    for name in MODEL_FEATURES_V2:
        values = features[name].to_numpy(dtype=float)
        rows.append(
            {
                "feature": name,
                "new_in_v2": name in NEW_IN_V2,
                "legit_median": round(float(legitimate[name].median()), 4),
                "legit_p90": round(float(legitimate[name].quantile(0.9)), 4),
                "attack_median": round(float(attack[name].median()), 4),
                "attack_p90": round(float(attack[name].quantile(0.9)), 4),
                "overlap": round(
                    _overlap_coefficient(
                        legitimate[name].to_numpy(dtype=float),
                        attack[name].to_numpy(dtype=float),
                    ),
                    4,
                ),
                "max_f1": round(max_univariate_f1(values, labels), 4),
                "zero_or_default_rate": round(float((values == 0.0).mean()), 4),
            }
        )
    return pd.DataFrame(rows)


def scenario_feature_table(
    features: pd.DataFrame, names: tuple[str, ...]
) -> pd.DataFrame:
    """Median of the named features per scenario family."""
    by_scenario = features.groupby(["population", "scenario"])
    grouped = by_scenario[list(names)].median()
    grouped["devices"] = by_scenario.device_id.nunique()
    grouped["requests"] = by_scenario.size()
    return grouped.round(3).reset_index()


def segment_table(features: pd.DataFrame, names: tuple[str, ...]) -> pd.DataFrame:
    """Feature medians by customer-identity segment and population."""
    working = features.copy()
    working["segment"] = np.where(
        working.customer_id_present.eq(1.0), "customer_present", "customer_absent"
    )
    working["group"] = np.where(working.label.eq(1), "attack", "legitimate")
    grouped = working.groupby(["segment", "group"])[list(names)].median()
    grouped["rows"] = working.groupby(["segment", "group"]).size()
    return grouped.round(3).reset_index()


def correlation_pairs(features: pd.DataFrame, threshold: float = 0.85) -> pd.DataFrame:
    """Highly correlated pairs, reported not removed.

    Model v1's coefficients showed sign instability from correlated inputs;
    Phase 10 needs to see the pairs before choosing a candidate, but nothing
    is dropped automatically here.
    """
    matrix = features.loc[:, list(MODEL_FEATURES_V2)].corr(method="spearman")
    rows = []
    names = list(MODEL_FEATURES_V2)
    for i, left in enumerate(names):
        for right in names[i + 1 :]:
            value = float(matrix.loc[left, right])
            if abs(value) >= threshold:
                rows.append({"left": left, "right": right, "spearman": round(value, 4)})
    return pd.DataFrame(rows).sort_values(
        "spearman", key=lambda s: s.abs(), ascending=False
    )


def validate_features_v2(features: pd.DataFrame) -> ValidationReport:
    report = ValidationReport()
    check_contract(features, report)
    check_univariate_leakage(features, report)
    check_shuffled_labels(features, report)
    check_overlap(features, report)
    check_customer_missingness(features, report)
    report.summary["model_trained"] = False
    return report
