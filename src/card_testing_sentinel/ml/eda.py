from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, precision_recall_curve

from card_testing_sentinel.features.specification import MODEL_FEATURES
from card_testing_sentinel.ml.weights import device_evaluation_weights


def training_eda(features: pd.DataFrame, raw: pd.DataFrame, output: Path) -> dict:
    if features.empty or raw.empty:
        raise ValueError("training EDA requires lifecycle and feature rows")
    output.mkdir(parents=True, exist_ok=True)
    weights = device_evaluation_weights(features)
    summary = {
        "scope": "training devices only",
        "devices": int(features.device_id.nunique()),
        "precheck_rows": int(len(features)),
        "sessions": int(raw.session_id.nunique()),
        "lifecycle_events": int(len(raw)),
        "label_devices": {
            str(key): int(value)
            for key, value in features.drop_duplicates("device_id")
            .groupby("label")
            .size()
            .items()
        },
        "label_rows": {
            str(key): int(value)
            for key, value in features.groupby("label").size().items()
        },
        "device_weighted_positive_rate": float(
            np.average(features.label, weights=weights)
        ),
        "row_weighted_positive_rate": float(features.label.mean()),
        "scenario_devices": {
            str(key): int(value)
            for key, value in features.drop_duplicates("device_id")
            .groupby("scenario_tag")
            .size()
            .items()
        },
        "subtype_devices": {
            str(key): int(value)
            for key, value in features.drop_duplicates("device_id")
            .dropna(subset=["attack_subtype"])
            .groupby("attack_subtype")
            .size()
            .items()
        },
        "requests_per_device": features.groupby("device_id")
        .size()
        .describe(percentiles=[0.5, 0.9, 0.99])
        .to_dict(),
        "sessions_per_device": raw.groupby("device_id")
        .session_id.nunique()
        .describe(percentiles=[0.5, 0.9, 0.99])
        .to_dict(),
        "event_type_counts": {
            str(key): int(value)
            for key, value in raw.groupby("event_type").size().items()
        },
    }
    feature_rows = []
    for name in MODEL_FEATURES:
        values = pd.to_numeric(features[name], errors="coerce")
        q1, q3 = values.quantile([0.25, 0.75])
        iqr = q3 - q1
        feature_rows.append(
            {
                "feature": name,
                "missing": int(values.isna().sum()),
                "nonfinite": int((~np.isfinite(values.dropna())).sum()),
                "unique": int(values.nunique(dropna=False)),
                "minimum": float(values.min()),
                "p01": float(values.quantile(0.01)),
                "p25": float(q1),
                "median": float(values.median()),
                "p75": float(q3),
                "p99": float(values.quantile(0.99)),
                "maximum": float(values.max()),
                "iqr_outliers": int(
                    ((values < q1 - 3 * iqr) | (values > q3 + 3 * iqr)).sum()
                ),
                "near_constant": bool(
                    values.value_counts(normalize=True, dropna=False).iloc[0] >= 0.995
                ),
            }
        )
    pd.DataFrame(feature_rows).to_csv(
        output / "training_feature_summary.csv", index=False
    )
    distribution = features.groupby(["scenario_tag", "attack_subtype"], dropna=False)[
        list(MODEL_FEATURES)
    ].agg(["mean", "median"])
    distribution.columns = ["__".join(value) for value in distribution.columns]
    distribution.reset_index().to_csv(
        output / "training_scenario_feature_distributions.csv", index=False
    )
    correlations = features.loc[:, MODEL_FEATURES].corr()
    correlations.to_csv(output / "training_feature_correlations.csv")
    high_pairs = [
        {
            "left": left,
            "right": right,
            "absolute_pearson": float(abs(correlations.loc[left, right])),
        }
        for index, left in enumerate(MODEL_FEATURES)
        for right in MODEL_FEATURES[index + 1 :]
        if abs(correlations.loc[left, right]) >= 0.95
    ]
    pd.DataFrame(high_pairs).to_csv(
        output / "training_high_correlation_pairs.csv", index=False
    )
    strength = []
    labels = features.label.to_numpy(dtype=int)
    for name in MODEL_FEATURES:
        values = features[name].to_numpy(dtype=float)
        best = None
        for direction, scores in ((">=", values), ("<=", -values)):
            precision, recall, thresholds = precision_recall_curve(
                labels, scores, sample_weight=weights
            )
            f1 = (
                2
                * precision[:-1]
                * recall[:-1]
                / np.maximum(precision[:-1] + recall[:-1], 1e-12)
            )
            idx = int(np.argmax(f1))
            row = {
                "feature": name,
                "direction": direction,
                "threshold": float(
                    thresholds[idx] if direction == ">=" else -thresholds[idx]
                ),
                "device_weighted_f1": float(f1[idx]),
                "device_weighted_pr_auc": float(
                    average_precision_score(labels, scores, sample_weight=weights)
                ),
            }
            if best is None or row["device_weighted_f1"] > best["device_weighted_f1"]:
                best = row
        strength.append(best)
    pd.DataFrame(strength).sort_values("device_weighted_f1", ascending=False).to_csv(
        output / "training_univariate_strength.csv", index=False
    )
    stability_rows = []
    if "fold" in features:
        for fold in sorted(features.fold.unique()):
            group = features.loc[features.fold.eq(fold)]
            for name in MODEL_FEATURES:
                stability_rows.append(
                    {
                        "fold": int(fold),
                        "feature": name,
                        "mean": float(group[name].mean()),
                        "std": float(group[name].std()),
                    }
                )
    pd.DataFrame(stability_rows, columns=["fold", "feature", "mean", "std"]).to_csv(
        output / "training_fold_feature_stability.csv", index=False
    )
    return summary
