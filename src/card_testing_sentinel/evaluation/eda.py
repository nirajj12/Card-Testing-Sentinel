"""Focused, deterministic exploratory analysis of training authorizations only."""

import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, precision_recall_curve

from card_testing_sentinel.common.exceptions import ModelTrainingError
from card_testing_sentinel.features.spec import MODEL_FEATURES
from card_testing_sentinel.modeling.data import ModelingView
from card_testing_sentinel.modeling.weights import evaluation_weights

matplotlib.use("Agg")
from matplotlib import pyplot as plt  # noqa: E402

SUMMARY_COLUMNS = (
    "feature",
    "non_null_count",
    "missing_count",
    "finite_value_count",
    "unique_value_count",
    "zero_value_share",
    "mean",
    "std",
    "min",
    "p01",
    "p05",
    "median",
    "p95",
    "p99",
    "max",
    "skewness",
    "near_constant",
)
SELECTED_FEATURES = (
    "attempts_trailing_60s",
    "unique_cards_trailing_60s",
    "decline_ratio_so_far",
    "amount_near_minimum_ratio_5min",
    "attempts_after_first_approval",
    "ip_device_count_trailing_5min",
)
logger = logging.getLogger(__name__)


def _atomic_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def feature_summary(
    X: pd.DataFrame, near_constant_share: float = 0.995
) -> pd.DataFrame:
    """Summarize the frozen allowlist without transforming values."""
    rows = []
    for feature in MODEL_FEATURES:
        series = X[feature].astype(float)
        finite = np.isfinite(series.to_numpy())
        mode_share = float(series.value_counts(normalize=True, dropna=False).iloc[0])
        rows.append(
            {
                "feature": feature,
                "non_null_count": int(series.notna().sum()),
                "missing_count": int(series.isna().sum()),
                "finite_value_count": int(finite.sum()),
                "unique_value_count": int(series.nunique(dropna=True)),
                "zero_value_share": float(series.eq(0).mean()),
                "mean": float(series.mean()),
                "std": float(series.std(ddof=1)),
                "min": float(series.min()),
                "p01": float(series.quantile(0.01)),
                "p05": float(series.quantile(0.05)),
                "median": float(series.median()),
                "p95": float(series.quantile(0.95)),
                "p99": float(series.quantile(0.99)),
                "max": float(series.max()),
                "skewness": float(series.skew()),
                "near_constant": bool(mode_share >= near_constant_share),
            }
        )
    return pd.DataFrame(rows, columns=SUMMARY_COLUMNS)


def feature_correlations(X: pd.DataFrame) -> pd.DataFrame:
    """Return each unique feature pair with Pearson and Spearman correlation."""
    pearson = X.corr(method="pearson")
    spearman = X.corr(method="spearman")
    rows = []
    for left_index, left in enumerate(MODEL_FEATURES):
        for right in MODEL_FEATURES[left_index + 1 :]:
            rows.append(
                {
                    "feature_left": left,
                    "feature_right": right,
                    "pearson": float(pearson.loc[left, right]),
                    "spearman": float(spearman.loc[left, right]),
                }
            )
    return pd.DataFrame(rows)


def univariate_strength(view: ModelingView) -> pd.DataFrame:
    """Audit both score directions using device-equal training weights."""
    weights = evaluation_weights(view.metadata["device_id"])
    rows = []
    for feature in MODEL_FEATURES:
        values = view.X[feature].to_numpy(dtype=float)
        candidates = []
        for direction, scores in (("high", values), ("low", -values)):
            ap = float(average_precision_score(view.y, scores, sample_weight=weights))
            precision, recall, thresholds = precision_recall_curve(
                view.y, scores, sample_weight=weights
            )
            f1 = np.divide(
                2 * precision * recall,
                precision + recall,
                out=np.zeros_like(precision),
                where=(precision + recall) > 0,
            )
            valid = np.arange(len(f1) - 1)
            best = int(valid[np.argmax(f1[:-1])]) if len(valid) else 0
            threshold = float(thresholds[best]) if len(thresholds) else float("inf")
            reported_threshold = threshold if direction == "high" else -threshold
            candidates.append((float(f1[best]), ap, direction, reported_threshold))
        best_f1, ap, direction, threshold = max(
            candidates, key=lambda item: (item[0], item[1], item[2] == "high")
        )
        rows.append(
            {
                "feature": feature,
                "direction": direction,
                "weighted_average_precision": ap,
                "best_weighted_f1": best_f1,
                "threshold": threshold,
                "shortcut_warning": best_f1 > 0.90,
            }
        )
    return (
        pd.DataFrame(rows)
        .sort_values(
            ["best_weighted_f1", "feature"], ascending=[False, True], kind="mergesort"
        )
        .reset_index(drop=True)
    )


def _group_counts(frame: pd.DataFrame, column: str) -> list[dict[str, Any]]:
    grouped = frame.groupby(column, dropna=False, observed=True)
    return [
        {
            column: str(key),
            "authorization_rows": int(len(part)),
            "unique_devices": int(part["device_id"].nunique()),
        }
        for key, part in sorted(grouped, key=lambda pair: str(pair[0]))
    ]


def scenario_membership(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Count session scenarios without collapsing returning-device overlap."""
    membership = frame[["session_id", "device_id", "scenario_tag"]].drop_duplicates()
    rows = []
    for scenario, part in sorted(
        membership.groupby("scenario_tag", dropna=False, observed=True),
        key=lambda pair: str(pair[0]),
    ):
        rows.append(
            {
                "scenario_tag": str(scenario),
                "sessions": int(part["session_id"].nunique()),
                "distinct_devices_ever_tagged": int(part["device_id"].nunique()),
            }
        )
    return rows


def _device_distribution(
    frame: pd.DataFrame, columns: list[str]
) -> list[dict[str, Any]]:
    counts = frame.groupby([*columns, "device_id"], dropna=False, observed=True).size()
    rows = []
    level = columns[0] if len(columns) == 1 else columns
    for keys, part in counts.groupby(level=level, observed=True):
        if not isinstance(keys, tuple):
            keys = (keys,)
        values = part.to_numpy(dtype=float)
        row = {column: str(value) for column, value in zip(columns, keys, strict=True)}
        row.update(
            {
                "devices": int(len(values)),
                "minimum": int(values.min()),
                "median": float(np.median(values)),
                "mean": float(values.mean()),
                "p95": float(np.quantile(values, 0.95)),
                "p99": float(np.quantile(values, 0.99)),
                "maximum": int(values.max()),
            }
        )
        rows.append(row)
    return sorted(rows, key=lambda row: tuple(row[column] for column in columns))


def _save_figures(
    frame: pd.DataFrame, correlations: pd.DataFrame, figure_dir: Path
) -> None:
    figure_dir.mkdir(parents=True, exist_ok=True)
    label_counts = frame.groupby("label").agg(
        rows=("event_id", "size"), devices=("device_id", "nunique")
    )
    fig, axes = plt.subplots(1, 2, figsize=(9, 4))
    label_counts["devices"].plot.bar(ax=axes[0], title="Training devices by label")
    label_counts["rows"].plot.bar(
        ax=axes[1], title="Training authorization rows by label"
    )
    for axis in axes:
        axis.set_xlabel("label")
        axis.set_ylabel("count")
    fig.tight_layout()
    fig.savefig(figure_dir / "training_device_vs_row_balance.png", dpi=150)
    plt.close(fig)

    counts = (
        frame.groupby(["device_id", "population"], observed=True)
        .size()
        .reset_index(name="authorizations")
    )
    fig, ax = plt.subplots(figsize=(8, 4.5))
    for population, part in counts.groupby("population", observed=True):
        ax.hist(
            part["authorizations"],
            bins=np.logspace(0, np.log10(counts["authorizations"].max() + 1), 25),
            histtype="step",
            density=True,
            linewidth=1.8,
            label=str(population),
        )
    ax.set_xscale("log")
    ax.set_xlabel("authorizations per device (log scale)")
    ax.set_ylabel("density")
    ax.legend()
    fig.tight_layout()
    fig.savefig(figure_dir / "training_authorizations_per_device.png", dpi=150)
    plt.close(fig)

    scenario = frame["scenario_tag"].fillna(
        frame["attack_subtype"].map(lambda value: f"attack_{value}")
    )
    fig, axes = plt.subplots(2, 3, figsize=(13, 7))
    for feature, axis in zip(SELECTED_FEATURES, axes.flat, strict=True):
        for name in sorted(scenario.dropna().unique()):
            values = frame.loc[scenario.eq(name), feature]
            axis.hist(
                values, bins=25, density=True, histtype="step", linewidth=1, label=name
            )
        axis.set_title(feature)
        axis.set_ylabel("row density")
    handles, labels = axes.flat[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="outside lower center", ncol=4, fontsize=8)
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    fig.savefig(figure_dir / "training_feature_distributions.png", dpi=150)
    plt.close(fig)

    matrix = frame.loc[:, MODEL_FEATURES].corr(method="spearman")
    fig, ax = plt.subplots(figsize=(12, 10))
    image = ax.imshow(matrix, vmin=-1, vmax=1, cmap="coolwarm")
    ax.set_xticks(range(len(MODEL_FEATURES)), MODEL_FEATURES, rotation=90, fontsize=7)
    ax.set_yticks(range(len(MODEL_FEATURES)), MODEL_FEATURES, fontsize=7)
    fig.colorbar(image, ax=ax, label="Spearman correlation")
    fig.tight_layout()
    fig.savefig(figure_dir / "training_feature_correlation.png", dpi=150)
    plt.close(fig)


def run_training_eda(
    view: ModelingView,
    *,
    checksums: dict[str, str],
    dataset_version: str,
    metrics_dir: Path,
    figure_dir: Path,
    near_constant_share: float = 0.995,
    shortcut_limit: float = 0.90,
) -> dict[str, Any]:
    """Run the mandatory training-only EDA gate and write approved artifacts."""
    logger.info("Starting training-only EDA")
    if "split" in view.metadata and not view.metadata["split"].eq("train").all():
        raise ModelTrainingError("EDA received non-training rows")
    if tuple(view.X.columns) != MODEL_FEATURES or len(view.X) != len(view.metadata):
        raise ModelTrainingError("EDA view violates the feature or row contract")
    frame = pd.concat([view.metadata, view.y, view.X], axis=1)
    metrics_dir.mkdir(parents=True, exist_ok=True)
    summary_table = feature_summary(view.X, near_constant_share)
    correlations = feature_correlations(view.X)
    strength = univariate_strength(view)
    summary_table.to_csv(
        metrics_dir / "training_feature_summary.csv", index=False, float_format="%.12g"
    )
    correlations.to_csv(
        metrics_dir / "training_feature_correlations.csv",
        index=False,
        float_format="%.12g",
    )
    strength.to_csv(
        metrics_dir / "training_univariate_strength.csv",
        index=False,
        float_format="%.12g",
    )
    _save_figures(frame, correlations, figure_dir)

    highly_correlated = correlations.loc[
        correlations[["pearson", "spearman"]].abs().max(axis=1).ge(0.95)
    ].to_dict("records")
    strongest = strength.iloc[0].to_dict()
    shortcut = bool(strength["best_weighted_f1"].gt(shortcut_limit).any())
    device_authorizations = frame.groupby("device_id").size()
    session_device = frame[
        ["session_id", "device_id", "scenario_tag"]
    ].drop_duplicates()
    sessions_per_device = session_device.groupby("device_id").size()
    scenario_counts = scenario_membership(frame)
    quantiles = device_authorizations.quantile([0, 0.5, 0.95, 0.99, 1]).to_dict()
    paths = {
        "feature_summary": "artifacts/metrics/training_feature_summary.csv",
        "feature_correlations": "artifacts/metrics/training_feature_correlations.csv",
        "univariate_strength": "artifacts/metrics/training_univariate_strength.csv",
        "figures": [
            f"reports/figures/{name}"
            for name in (
                "training_device_vs_row_balance.png",
                "training_authorizations_per_device.png",
                "training_feature_distributions.png",
                "training_feature_correlation.png",
            )
        ],
    }
    payload = {
        "dataset_version": dataset_version,
        "frozen_checksums": checksums,
        "analyzed_split": "train",
        "authorization_rows": int(len(frame)),
        "unique_devices": int(frame["device_id"].nunique()),
        "validation_rows": 0,
        "test_rows": 0,
        "counts_by_label": _group_counts(frame, "label"),
        "counts_by_population": _group_counts(frame, "population"),
        "counts_by_attacker_subtype": _group_counts(
            frame.loc[frame["label"].eq(1)], "attack_subtype"
        ),
        "scenario_membership": scenario_counts,
        "authorizations_per_device_by_population": _device_distribution(
            frame, ["population"]
        ),
        "authorizations_per_device_by_attacker_subtype": _device_distribution(
            frame.loc[frame["label"].eq(1)], ["attack_subtype"]
        ),
        "sessions": int(frame["session_id"].nunique()),
        "sessions_per_device": {
            "minimum": int(sessions_per_device.min()),
            "median": float(sessions_per_device.median()),
            "mean": float(sessions_per_device.mean()),
            "p95": float(sessions_per_device.quantile(0.95)),
            "p99": float(sessions_per_device.quantile(0.99)),
            "maximum": int(sessions_per_device.max()),
        },
        "authorizations_per_device": {
            "minimum": int(quantiles[0.0]),
            "median": float(quantiles[0.5]),
            "mean": float(device_authorizations.mean()),
            "p95": float(quantiles[0.95]),
            "p99": float(quantiles[0.99]),
            "maximum": int(quantiles[1.0]),
        },
        "strongest_single_feature": strongest,
        "shortcut_warning": shortcut,
        "near_constant_features": summary_table.loc[
            summary_table["near_constant"], "feature"
        ].tolist(),
        "highly_correlated_feature_pairs": highly_correlated,
        "hard_negative_observations": {
            str(group): {
                feature: float(part[feature].median()) for feature in SELECTED_FEATURES
            }
            for group, part in frame.assign(
                analysis_group=frame["scenario_tag"]
            ).groupby("analysis_group", observed=True)
        },
        "artifacts": paths,
        "overall_status": "blocked" if shortcut else "passed",
    }
    _atomic_json(payload, metrics_dir / "training_eda_summary.json")
    if shortcut:
        raise ModelTrainingError(
            "EDA shortcut guardrail blocked training: single-feature F1 exceeds 0.90"
        )
    logger.info(
        "Training-only EDA passed with %d rows and %d devices",
        len(frame),
        frame["device_id"].nunique(),
    )
    return payload


def eda_summary_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
