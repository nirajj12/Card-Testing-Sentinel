"""Explicit grouped-CV training and validation-only model selection."""

import hashlib
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

import joblib
import matplotlib
import mlflow
import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    precision_recall_curve,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedGroupKFold

from card_testing_sentinel.common.exceptions import ModelTrainingError
from card_testing_sentinel.evaluation.eda import eda_summary_hash
from card_testing_sentinel.evaluation.metrics import (
    classification_metrics,
    subgroup_metrics,
)
from card_testing_sentinel.evaluation.thresholds import select_operating_point
from card_testing_sentinel.features.spec import MODEL_FEATURES
from card_testing_sentinel.modeling.data import ModelingView
from card_testing_sentinel.modeling.models import (
    build_hist_gradient_boosting,
    build_logistic_regression,
)
from card_testing_sentinel.modeling.weights import evaluation_weights, training_weights
from card_testing_sentinel.rules.baseline import SIGNALS, score_rules

matplotlib.use("Agg")
from matplotlib import pyplot as plt  # noqa: E402

logger = logging.getLogger(__name__)


def _json_write(payload: dict[str, Any], path: Path) -> None:
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


def require_current_eda(path: Path, checksums: dict[str, str]) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ModelTrainingError(
            "passed training EDA summary is required before fitting"
        ) from exc
    if (
        payload.get("overall_status") != "passed"
        or payload.get("frozen_checksums") != checksums
    ):
        raise ModelTrainingError("training EDA summary is blocked or checksum-stale")
    if payload.get("validation_rows") != 0 or payload.get("test_rows") != 0:
        raise ModelTrainingError("training EDA summary contains held-out rows")
    return payload


def _builder(family: str, config: dict, seed: int):
    if family == "logistic_regression":
        return build_logistic_regression(float(config["C"]), seed)
    return build_hist_gradient_boosting(config, seed)


def _fit(
    model, family: str, X: pd.DataFrame, y: pd.Series, weights: np.ndarray
) -> None:
    if family == "logistic_regression":
        model.fit(X, y, logistic_regression__sample_weight=weights)
    else:
        model.fit(X, y, sample_weight=weights)


def grouped_cross_validation(
    view: ModelingView, config: dict, seed: int
) -> tuple[pd.DataFrame, dict[str, dict]]:
    folds = StratifiedGroupKFold(
        n_splits=int(config["cross_validation_folds"]), shuffle=True, random_state=seed
    )
    candidates = [
        ("logistic_regression", item) for item in config["logistic_candidates"]
    ]
    candidates += [
        ("hist_gradient_boosting", item)
        for item in config["hist_gradient_boosting_candidates"]
    ]
    rows = []
    split_indices = list(folds.split(view.X, view.y, groups=view.metadata["device_id"]))
    for family, candidate in candidates:
        for fold_number, (fit_index, holdout_index) in enumerate(
            split_indices, start=1
        ):
            logger.info(
                "Cross-validation candidate=%s fold=%d", candidate["name"], fold_number
            )
            fit_devices = view.metadata.iloc[fit_index]["device_id"]
            holdout_devices = view.metadata.iloc[holdout_index]["device_id"]
            overlap = len(set(fit_devices) & set(holdout_devices))
            if overlap:
                raise ModelTrainingError(
                    "device overlap found in grouped cross-validation"
                )
            train_weight = training_weights(
                fit_devices.reset_index(drop=True),
                view.y.iloc[fit_index].reset_index(drop=True),
            )
            evaluate_weight = evaluation_weights(holdout_devices.reset_index(drop=True))
            model = _builder(family, candidate, seed)
            start = time.perf_counter()
            _fit(
                model,
                family,
                view.X.iloc[fit_index],
                view.y.iloc[fit_index],
                train_weight,
            )
            fit_time = time.perf_counter() - start
            start = time.perf_counter()
            scores = model.predict_proba(view.X.iloc[holdout_index])[:, 1]
            score_time = time.perf_counter() - start
            rows.append(
                {
                    "model_family": family,
                    "candidate": candidate["name"],
                    "fold": fold_number,
                    "fit_rows": len(fit_index),
                    "holdout_rows": len(holdout_index),
                    "fit_devices": int(fit_devices.nunique()),
                    "holdout_devices": int(holdout_devices.nunique()),
                    "device_overlap": overlap,
                    "average_precision": float(
                        average_precision_score(
                            view.y.iloc[holdout_index],
                            scores,
                            sample_weight=evaluate_weight,
                        )
                    ),
                    "roc_auc": float(
                        roc_auc_score(
                            view.y.iloc[holdout_index],
                            scores,
                            sample_weight=evaluate_weight,
                        )
                    ),
                    "fit_time_seconds": fit_time,
                    "score_time_seconds": score_time,
                }
            )
    results = pd.DataFrame(rows)
    selected: dict[str, dict] = {}
    for family in ("logistic_regression", "hist_gradient_boosting"):
        part = results.loc[results["model_family"].eq(family)]
        aggregate = part.groupby("candidate", as_index=False).agg(
            mean_average_precision=("average_precision", "mean"),
            std_average_precision=("average_precision", "std"),
            mean_fit_time=("fit_time_seconds", "mean"),
        )
        aggregate = aggregate.sort_values(
            [
                "mean_average_precision",
                "std_average_precision",
                "mean_fit_time",
                "candidate",
            ],
            ascending=[False, True, True, True],
            kind="mergesort",
        )
        name = aggregate.iloc[0]["candidate"]
        source = (
            config["logistic_candidates"]
            if family == "logistic_regression"
            else config["hist_gradient_boosting_candidates"]
        )
        selected[family] = next(item for item in source if item["name"] == name)
    return results, selected


def _plots(
    validation: ModelingView,
    probabilities: dict[str, np.ndarray],
    operating: pd.DataFrame,
    champion: str,
    champion_metrics: dict[str, float],
    figure_dir: Path,
) -> None:
    figure_dir.mkdir(parents=True, exist_ok=True)
    weights = evaluation_weights(validation.metadata["device_id"])
    fig, ax = plt.subplots(figsize=(6.5, 5))
    for family in ("logistic_regression", "hist_gradient_boosting"):
        precision, recall, _ = precision_recall_curve(
            validation.y, probabilities[family], sample_weight=weights
        )
        ax.plot(recall, precision, label=family.replace("_", " "))
    ax.set(
        xlabel="device-weighted authorization-row recall",
        ylabel="precision",
        title="Validation precision-recall",
    )
    ax.legend()
    fig.tight_layout()
    fig.savefig(figure_dir / "validation_precision_recall.png", dpi=150)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(6.5, 5))
    for method, part in operating.groupby("method", sort=True):
        feasible = part[part["feasible"]]
        ax.plot(
            feasible["budget"],
            feasible["recall"],
            marker="o",
            label=method.replace("_", " "),
        )
    ax.set(
        xlabel="legitimate false-positive budget",
        ylabel="attacker row recall",
        title="Validation matched-FPR tradeoff",
    )
    ax.legend()
    fig.tight_layout()
    fig.savefig(figure_dir / "validation_fpr_tradeoff.png", dpi=150)
    plt.close(fig)
    matrix = np.array(
        [
            [
                champion_metrics["true_negative_weight"],
                champion_metrics["false_positive_weight"],
            ],
            [
                champion_metrics["false_negative_weight"],
                champion_metrics["true_positive_weight"],
            ],
        ]
    )
    fig, ax = plt.subplots(figsize=(5, 4))
    image = ax.imshow(matrix, cmap="Blues")
    for row in range(2):
        for column in range(2):
            ax.text(column, row, f"{matrix[row, column]:.2f}", ha="center", va="center")
    ax.set_xticks([0, 1], ["predicted 0", "predicted 1"])
    ax.set_yticks([0, 1], ["actual 0", "actual 1"])
    ax.set_title(f"{champion.replace('_', ' ')} at primary budget")
    fig.colorbar(image, ax=ax)
    fig.tight_layout()
    fig.savefig(figure_dir / "validation_confusion_matrix.png", dpi=150)
    plt.close(fig)


def run_training(
    train: ModelingView,
    validation: ModelingView,
    *,
    config: dict,
    seed: int,
    checksums: dict[str, str],
    dataset_version: str,
    eda_path: Path,
    artifacts_dir: Path,
    figure_dir: Path,
    mlflow_dir: Path,
) -> dict[str, Any]:
    """Fit approved candidates and compare them using validation only."""
    logger.info(
        "Starting Phase 3 training with %d train rows and %d validation rows",
        len(train.X),
        len(validation.X),
    )
    require_current_eda(eda_path, checksums)
    metrics_dir = artifacts_dir / "metrics"
    model_dir = artifacts_dir / "models"
    prediction_dir = artifacts_dir / "predictions"
    for directory in (metrics_dir, model_dir, prediction_dir, mlflow_dir):
        directory.mkdir(parents=True, exist_ok=True)
    cv, selected = grouped_cross_validation(train, config, seed)
    cv.sort_values(["model_family", "candidate", "fold"], inplace=True)
    cv.to_csv(
        metrics_dir / "cross_validation_results.csv", index=False, float_format="%.12g"
    )
    train_weight = training_weights(train.metadata["device_id"], train.y)
    models = {}
    probabilities = {}
    for family in ("logistic_regression", "hist_gradient_boosting"):
        model = _builder(family, selected[family], seed)
        _fit(model, family, train.X, train.y, train_weight)
        models[family] = model
        probabilities[family] = model.predict_proba(validation.X)[:, 1]
        joblib.dump(
            model,
            model_dir
            / (
                "logistic_regression.joblib"
                if family == "logistic_regression"
                else "hist_gradient_boosting.joblib"
            ),
        )
    rules = score_rules(validation.X, config)
    probabilities["rules"] = rules["rule_score"].to_numpy(dtype=float)
    weights = evaluation_weights(validation.metadata["device_id"])
    operating_rows = []
    for method in ("rules", "logistic_regression", "hist_gradient_boosting"):
        for budget in config["false_positive_budgets"]:
            point = select_operating_point(
                validation.y, probabilities[method], weights, float(budget)
            )
            operating_rows.append({"method": method, **point})
    operating = pd.DataFrame(operating_rows)
    operating.to_csv(
        metrics_dir / "validation_operating_points.csv",
        index=False,
        float_format="%.12g",
    )
    primary_budget = float(config["primary_false_positive_budget"])
    primary = operating.loc[operating["budget"].eq(primary_budget)].set_index("method")
    if not primary.loc[
        ["logistic_regression", "hist_gradient_boosting"], "feasible"
    ].all():
        raise ModelTrainingError(
            "an ML candidate has no feasible primary operating point"
        )
    ranking = {}
    for family in ("logistic_regression", "hist_gradient_boosting"):
        threshold = float(primary.loc[family, "threshold"])
        metrics = classification_metrics(
            validation.y, probabilities[family], threshold, weights
        )
        metrics["subgroups"] = subgroup_metrics(
            validation.metadata, validation.y, probabilities[family], threshold, weights
        )
        metrics["default_0_5_reference"] = classification_metrics(
            validation.y, probabilities[family], 0.5, weights, ranking=False
        )
        ranking[family] = metrics
    rule_threshold = (
        float(primary.loc["rules", "threshold"])
        if bool(primary.loc["rules", "feasible"])
        else float("inf")
    )
    rule_metrics = classification_metrics(
        validation.y,
        probabilities["rules"],
        rule_threshold,
        weights,
        ranking=False,
    )
    rule_metrics["subgroups"] = subgroup_metrics(
        validation.metadata,
        validation.y,
        probabilities["rules"],
        rule_threshold,
        weights,
    )
    champion = max(
        ("logistic_regression", "hist_gradient_boosting"),
        key=lambda family: (
            ranking[family]["recall"],
            ranking[family]["precision"],
            ranking[family]["average_precision"],
            family == "logistic_regression",
        ),
    )
    logger.info("Selected validation-stage champion: %s", champion)
    feature_hash = hashlib.sha256("\n".join(MODEL_FEATURES).encode()).hexdigest()
    validation_counts = {
        "authorization_rows": len(validation.X),
        "unique_devices": int(validation.metadata["device_id"].nunique()),
        "positive_devices": int(
            validation.metadata.loc[validation.y.eq(1), "device_id"].nunique()
        ),
        "legitimate_devices": int(
            validation.metadata.loc[validation.y.eq(0), "device_id"].nunique()
        ),
        "by_population": [
            {
                "population": str(name),
                "authorization_rows": int(len(part)),
                "unique_devices": int(part["device_id"].nunique()),
            }
            for name, part in validation.metadata.groupby("population", observed=True)
        ],
    }
    validation_metrics = {
        "metric_unit": "device-weighted authorization rows",
        "validation_counts": validation_counts,
        "primary_false_positive_budget": primary_budget,
        "methods": {"rules": rule_metrics, **ranking},
    }
    _json_write(validation_metrics, metrics_dir / "validation_metrics.json")
    champion_metadata = {
        "model_family": champion,
        "model_filename": "logistic_regression.joblib"
        if champion == "logistic_regression"
        else "hist_gradient_boosting.joblib",
        "threshold": ranking[champion]["threshold"],
        "feature_order": list(MODEL_FEATURES),
        "feature_hash": feature_hash,
        "dataset_version": dataset_version,
        "frozen_checksums": checksums,
        "random_seed": seed,
        "training_weight": (
            "inverse authorization rows per device times inverse device class "
            "frequency; normalized mean 1"
        ),
        "selection_rule": (
            "highest recall, precision, PR-AUC at validation 3% legitimate FPR; "
            "simpler model tie-break"
        ),
        "validation_metrics": ranking[champion],
    }
    _json_write(champion_metadata, model_dir / "champion_metadata.json")
    predictions = validation.metadata.copy()
    predictions["true_label"] = validation.y
    for signal in SIGNALS:
        predictions[f"rule_{signal}"] = rules[signal].to_numpy()
    predictions["rule_score"] = rules["rule_score"].to_numpy()
    predictions["rule_reason_codes"] = rules["reason_codes"].to_numpy()
    predictions["logistic_regression_probability"] = probabilities[
        "logistic_regression"
    ]
    predictions["hist_gradient_boosting_probability"] = probabilities[
        "hist_gradient_boosting"
    ]
    predictions["champion_probability"] = probabilities[champion]
    for method in ("rules", "logistic_regression", "hist_gradient_boosting"):
        threshold = (
            float(primary.loc[method, "threshold"])
            if bool(primary.loc[method, "feasible"])
            else np.inf
        )
        predictions[f"{method}_primary_prediction"] = probabilities[method] >= threshold
    predictions.to_csv(
        prediction_dir / "validation_predictions.csv", index=False, float_format="%.12g"
    )
    _plots(
        validation, probabilities, operating, champion, ranking[champion], figure_dir
    )

    os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")
    mlflow.set_tracking_uri(mlflow_dir.resolve().as_uri())
    mlflow.set_experiment("card-testing-sentinel-baselines")
    eda_hash = eda_summary_hash(eda_path)
    run_ids = []
    for family, candidate_key in (
        ("logistic_regression", "logistic_candidates"),
        ("hist_gradient_boosting", "hist_gradient_boosting_candidates"),
    ):
        for candidate in config[candidate_key]:
            candidate_rows = cv.loc[
                cv["model_family"].eq(family) & cv["candidate"].eq(candidate["name"])
            ]
            with mlflow.start_run(run_name=f"cv-{candidate['name']}") as active:
                run_ids.append(active.info.run_id)
                mlflow.log_params(
                    {
                        "model_family": family,
                        "candidate": candidate["name"],
                        "seed": seed,
                        "dataset_version": dataset_version,
                        "fold_strategy": "3-fold StratifiedGroupKFold by device",
                        "sample_weight_strategy": (
                            "device_equal_and_device_class_balanced"
                        ),
                        **{
                            f"model_{key}": value
                            for key, value in candidate.items()
                            if key != "name"
                        },
                    }
                )
                mlflow.log_metrics(
                    {
                        "cv_mean_average_precision": float(
                            candidate_rows["average_precision"].mean()
                        ),
                        "cv_std_average_precision": float(
                            candidate_rows["average_precision"].std()
                        ),
                        "cv_mean_roc_auc": float(candidate_rows["roc_auc"].mean()),
                    }
                )
    for family, candidate in selected.items():
        with mlflow.start_run(run_name=f"selected-{family}") as active:
            run_ids.append(active.info.run_id)
            mlflow.log_params(
                {
                    "model_family": family,
                    "candidate": candidate["name"],
                    "seed": seed,
                    "dataset_version": dataset_version,
                    "feature_count": len(MODEL_FEATURES),
                    "feature_hash": feature_hash,
                    "eda_summary_hash": eda_hash,
                    "sample_weight_strategy": "device_equal_and_device_class_balanced",
                }
            )
            mlflow.log_metrics(
                {
                    f"validation_{key}": value
                    for key, value in ranking[family].items()
                    if isinstance(value, float)
                }
            )
            mlflow.log_artifact(
                str(
                    model_dir
                    / (
                        "logistic_regression.joblib"
                        if family == "logistic_regression"
                        else "hist_gradient_boosting.joblib"
                    )
                )
            )
    logger.info("Completed Phase 3 training; artifacts=%s", artifacts_dir)
    return {
        "champion": champion,
        "selected": selected,
        "validation_metrics": validation_metrics,
        "cross_validation": cv,
        "operating_points": operating,
        "eda_hash": eda_hash,
        "mlflow_run_ids": run_ids,
    }
