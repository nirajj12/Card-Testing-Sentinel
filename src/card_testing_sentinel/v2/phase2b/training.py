"""Isolated Phase 2B training-only pipeline."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import scipy
import sklearn
import yaml
from mlflow.entities import Metric, Param, RunStatus
from mlflow.store.tracking.file_store import FileStore
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import precision_recall_curve, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from card_testing_sentinel.common.atomic_io import atomic_write_json, atomic_write_text
from card_testing_sentinel.v2.evaluation.access import (
    verify_phase1_protected_inputs,
    verify_training_freeze,
    verify_v1_release,
)
from card_testing_sentinel.v2.evaluation.calibration import (
    apply_calibrator,
    fit_calibrator,
)
from card_testing_sentinel.v2.evaluation.metrics import (
    probability_metrics,
    reliability_table,
)
from card_testing_sentinel.v2.modeling.folds import (
    assert_fold_integrity,
    make_device_folds,
)
from card_testing_sentinel.v2.modeling.weights import (
    balanced_device_training_weights,
    device_evaluation_weights,
    weight_audit,
)
from card_testing_sentinel.v2.phase2b.artifacts import Phase2BModelArtifact
from card_testing_sentinel.v2.phase2b.batch import replay_training_events
from card_testing_sentinel.v2.phase2b.features import (
    MODEL_FEATURE_COLUMNS,
    MODEL_FEATURE_COLUMNS_SHA256,
    NEW_FEATURES,
    validate_model_feature_contract,
)
from card_testing_sentinel.v2.policy.selection import enumerate_policy_grid

ROOT = Path(__file__).resolve().parents[4]
SCENARIOS = (
    "normal_standard",
    "normal_bad_luck",
    "flash_standard",
    "flash_hard_retry",
    "attack_burst",
    "attack_evasive",
    "attack_patient",
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _csv(frame: pd.DataFrame) -> str:
    return frame.to_csv(index=False, float_format="%.12g", lineterminator="\n")


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    atomic_write_text(path, _csv(frame))


def _atomic_joblib_dump(value: object, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}."
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        joblib.dump(value, temporary)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def load_training_partition(root: Path = ROOT) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load only training devices from the protected combined development files."""
    verify_phase1_protected_inputs()
    splits = pd.read_csv(root / "data/v2/development/device_splits.csv")
    if set(splits.split) != {"train", "validation"}:
        raise RuntimeError("development split contract changed")
    if splits.device_id.duplicated().any():
        raise RuntimeError("duplicate device split assignment")
    train_splits = splits.loc[splits.split.eq("train")].copy()
    validation_ids = set(splits.loc[splits.split.eq("validation"), "device_id"])
    if set(train_splits.device_id) & validation_ids:
        raise RuntimeError("training and validation devices overlap")
    train_ids = set(train_splits.device_id)
    raw = pd.read_csv(root / "data/v2/development/raw_events.csv")
    raw = raw.loc[raw.device_id.isin(train_ids)].copy()
    if set(raw.device_id) != train_ids:
        raise RuntimeError("training raw-event boundary is incomplete")
    if raw.event_id.duplicated().any() or raw.request_id.isna().all():
        raise RuntimeError("duplicate event identity or missing request identity")
    if raw.groupby("device_id").label.nunique().max() != 1:
        raise RuntimeError("device label is not stable")
    if raw.groupby("device_id").scenario_tag.nunique().max() != 1:
        raise RuntimeError("device scenario metadata is not stable")
    return raw, train_splits


def generate_training_features(
    raw: pd.DataFrame, tolerance: float
) -> tuple[pd.DataFrame, dict]:
    first, latency = replay_training_events(raw, measure_latency=True)
    second, _ = replay_training_events(raw)
    first = first.sort_values(["timestamp", "event_id"], kind="mergesort").reset_index(
        drop=True
    )
    second = second.sort_values(
        ["timestamp", "event_id"], kind="mergesort"
    ).reset_index(drop=True)
    if first[["event_id", "request_id"]].to_dict("records") != second[
        ["event_id", "request_id"]
    ].to_dict("records"):
        raise RuntimeError("online/batch replay identity mismatch")
    differences = np.abs(
        first.loc[:, MODEL_FEATURE_COLUMNS].to_numpy(dtype=float)
        - second.loc[:, MODEL_FEATURE_COLUMNS].to_numpy(dtype=float)
    )
    mismatched = differences > tolerance
    report = {
        "rows_compared": len(first),
        "features_compared": len(MODEL_FEATURE_COLUMNS),
        "maximum_absolute_difference": float(differences.max(initial=0.0)),
        "mismatched_rows": int(mismatched.any(axis=1).sum()),
        "mismatched_features": int(mismatched.any(axis=0).sum()),
        "tolerance": tolerance,
        "latency_microseconds": {
            "p50": float(np.percentile(latency, 50) / 1000),
            "p95": float(np.percentile(latency, 95) / 1000),
            "p99": float(np.percentile(latency, 99) / 1000),
            "diagnostic_only": True,
        },
    }
    if report["mismatched_rows"] or report["mismatched_features"]:
        raise RuntimeError(f"Phase 2B online/batch parity failed: {report}")
    values = first.loc[:, MODEL_FEATURE_COLUMNS].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise RuntimeError("Phase 2B model input contains NaN or infinity")
    return first, report


def make_candidate_specs(config: dict) -> list[dict]:
    specs = []
    logistic = config["candidate_grids"]["logistic_regression"]
    for value in logistic["C"]:
        specs.append(
            {
                "family": "logistic_regression",
                "parameters": {
                    "C": float(value),
                    "max_iter": int(logistic["max_iter"]),
                },
            }
        )
    specs.extend(
        {"family": "hist_gradient_boosting", "parameters": dict(parameters)}
        for parameters in config["candidate_grids"]["hist_gradient_boosting"]
    )
    return specs


def build_candidate(spec: dict, seed: int):
    if spec["family"] == "logistic_regression":
        numeric = Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler()),
            ]
        )
        preprocessing = ColumnTransformer(
            [("numeric", numeric, list(MODEL_FEATURE_COLUMNS))],
            remainder="drop",
            verbose_feature_names_out=False,
        )
        return Pipeline(
            [
                ("preprocessing", preprocessing),
                (
                    "classifier",
                    LogisticRegression(
                        C=spec["parameters"]["C"],
                        max_iter=spec["parameters"]["max_iter"],
                        random_state=seed,
                    ),
                ),
            ]
        )
    return HistGradientBoostingClassifier(
        **spec["parameters"], random_state=seed, early_stopping=False
    )


def fit_candidate(model, spec: dict, frame: pd.DataFrame, weights: np.ndarray):
    x = frame.loc[:, MODEL_FEATURE_COLUMNS]
    if tuple(x.columns) != MODEL_FEATURE_COLUMNS:
        raise RuntimeError("model.fit did not receive the explicit Phase 2B allowlist")
    if spec["family"] == "logistic_regression":
        model.fit(x, frame.label, classifier__sample_weight=weights)
    else:
        model.fit(x, frame.label, sample_weight=weights)
    return model


def diagnostic_device_threshold(
    frame: pd.DataFrame, probabilities: np.ndarray, rate: float
) -> tuple[float, pd.DataFrame]:
    scored = frame[["device_id", "label", "attack_subtype", "scenario_tag"]].copy()
    scored["probability"] = probabilities
    devices = scored.groupby("device_id", as_index=False).agg(
        label=("label", "first"),
        attack_subtype=("attack_subtype", "first"),
        scenario_tag=("scenario_tag", "first"),
        maximum_probability=("probability", "max"),
    )
    legitimate = devices.loc[devices.label.eq(0), "maximum_probability"].sort_values(
        ascending=False
    )
    allowance = int(np.floor(len(legitimate) * rate))
    threshold = (
        1.0
        if allowance == 0
        else float(np.nextafter(legitimate.iloc[allowance - 1], np.inf))
    )
    devices["acted"] = devices.maximum_probability >= threshold
    return threshold, devices


def device_diagnostics(devices: pd.DataFrame) -> dict:
    attackers = devices.loc[devices.label.eq(1)]
    subtype = {
        str(name): {
            "numerator": int(group.acted.sum()),
            "denominator": int(len(group)),
            "coverage": float(group.acted.mean()),
        }
        for name, group in attackers.groupby("attack_subtype", sort=True)
    }
    scenario = {
        str(name): {
            "acted_devices": int(group.acted.sum()),
            "devices": int(len(group)),
            "rate": float(group.acted.mean()),
        }
        for name, group in devices.groupby("scenario_tag", sort=True)
    }
    coverages = [value["coverage"] for value in subtype.values()]
    return {
        "subtype": subtype,
        "scenario": scenario,
        "worst_subtype_coverage": min(coverages),
        "macro_subtype_coverage": float(np.mean(coverages)),
    }


def grouped_oof(
    frame: pd.DataFrame, spec: dict, seed: int
) -> tuple[np.ndarray, list[dict], float]:
    probabilities = np.full(len(frame), np.nan, dtype=float)
    fold_rows = []
    started = time.perf_counter()
    for fold in sorted(frame.fold.unique()):
        fit_mask = frame.fold.ne(fold)
        holdout_mask = ~fit_mask
        fit_devices = set(frame.loc[fit_mask, "device_id"])
        holdout_devices = set(frame.loc[holdout_mask, "device_id"])
        if fit_devices & holdout_devices:
            raise RuntimeError("OOF device overlap")
        model = build_candidate(spec, seed)
        fit_candidate(
            model,
            spec,
            frame.loc[fit_mask],
            balanced_device_training_weights(frame.loc[fit_mask]),
        )
        probabilities[holdout_mask] = model.predict_proba(
            frame.loc[holdout_mask, MODEL_FEATURE_COLUMNS]
        )[:, 1]
        metrics = probability_metrics(
            frame.loc[holdout_mask, "label"],
            probabilities[holdout_mask],
            device_evaluation_weights(frame.loc[holdout_mask]),
        )
        fold_rows.append(
            {
                "fold": int(fold),
                "fit_devices": len(fit_devices),
                "holdout_devices": len(holdout_devices),
                "device_overlap": 0,
                **metrics,
            }
        )
    if np.isnan(probabilities).any():
        raise RuntimeError("not every training row received one OOF prediction")
    return probabilities, fold_rows, time.perf_counter() - started


def nested_calibrated_oof(
    frame: pd.DataFrame, spec: dict, method: str, seed: int
) -> tuple[np.ndarray, np.ndarray, list[dict]]:
    raw = np.full(len(frame), np.nan, dtype=float)
    calibrated = np.full(len(frame), np.nan, dtype=float)
    isolation = []
    folds = sorted(frame.fold.unique())
    for outer in folds:
        outer_mask = frame.fold.eq(outer)
        calibration_fold = folds[(folds.index(outer) + 1) % len(folds)]
        calibration_mask = frame.fold.eq(calibration_fold)
        base_mask = ~(outer_mask | calibration_mask)
        roles = [
            set(frame.loc[mask, "device_id"])
            for mask in (base_mask, calibration_mask, outer_mask)
        ]
        if roles[0] & roles[1] or roles[0] & roles[2] or roles[1] & roles[2]:
            raise RuntimeError("nested calibration device isolation failed")
        base = build_candidate(spec, seed)
        fit_candidate(
            base,
            spec,
            frame.loc[base_mask],
            balanced_device_training_weights(frame.loc[base_mask]),
        )
        calibration_raw = base.predict_proba(
            frame.loc[calibration_mask, MODEL_FEATURE_COLUMNS]
        )[:, 1]
        calibrator = fit_calibrator(
            method,
            calibration_raw,
            frame.loc[calibration_mask, "label"].to_numpy(),
            device_evaluation_weights(frame.loc[calibration_mask]),
        )
        raw[outer_mask] = base.predict_proba(
            frame.loc[outer_mask, MODEL_FEATURE_COLUMNS]
        )[:, 1]
        calibrated[outer_mask] = apply_calibrator(method, calibrator, raw[outer_mask])
        isolation.append(
            {
                "outer_fold": int(outer),
                "base_fit_devices": len(roles[0]),
                "calibrator_fit_devices": len(roles[1]),
                "evaluation_devices": len(roles[2]),
                "all_pairwise_device_overlaps": 0,
            }
        )
    if np.isnan(raw).any() or np.isnan(calibrated).any():
        raise RuntimeError("calibrated OOF coverage is incomplete")
    return raw, calibrated, isolation


def fit_deployable(
    frame: pd.DataFrame, spec: dict, method: str, seed: int
) -> Phase2BModelArtifact:
    calibration_mask = (
        np.zeros(len(frame), dtype=bool)
        if method == "none"
        else frame.fold.eq(0).to_numpy()
    )
    base_mask = ~calibration_mask
    model = build_candidate(spec, seed)
    fit_candidate(
        model,
        spec,
        frame.loc[base_mask],
        balanced_device_training_weights(frame.loc[base_mask]),
    )
    calibrator = None
    if method != "none":
        raw = model.predict_proba(frame.loc[calibration_mask, MODEL_FEATURE_COLUMNS])[
            :, 1
        ]
        calibrator = fit_calibrator(
            method,
            raw,
            frame.loc[calibration_mask, "label"].to_numpy(),
            device_evaluation_weights(frame.loc[calibration_mask]),
        )
    return Phase2BModelArtifact(
        model, calibrator, method, spec["family"], spec["parameters"]
    )


def strongest_single_feature(frame: pd.DataFrame) -> dict:
    weights = device_evaluation_weights(frame)
    labels = frame.label.to_numpy(dtype=int)
    best = {"feature": "", "direction": "", "threshold": 0.0, "f1": -1.0}
    for feature in MODEL_FEATURE_COLUMNS:
        values = frame[feature].to_numpy(dtype=float)
        for direction, scores in ((">=", values), ("<=", -values)):
            precision, recall, thresholds = precision_recall_curve(
                labels, scores, sample_weight=weights
            )
            scores_f1 = (
                2
                * precision[:-1]
                * recall[:-1]
                / np.maximum(precision[:-1] + recall[:-1], 1e-12)
            )
            index = int(np.argmax(scores_f1))
            if scores_f1[index] > best["f1"]:
                threshold = float(thresholds[index])
                best = {
                    "feature": feature,
                    "direction": direction,
                    "threshold": threshold if direction == ">=" else -threshold,
                    "f1": float(scores_f1[index]),
                }
    return best


def scenario_shortcut_check(frame: pd.DataFrame) -> dict:
    weights = device_evaluation_weights(frame)
    strongest = {"feature": "", "scenario": "", "f1": -1.0}
    for feature in NEW_FEATURES:
        values = frame[feature].to_numpy(dtype=float)
        for scenario in SCENARIOS:
            labels = frame.scenario_tag.eq(scenario).to_numpy(dtype=int)
            for scores in (values, -values):
                precision, recall, _ = precision_recall_curve(
                    labels, scores, sample_weight=weights
                )
                scores_f1 = (
                    2
                    * precision[:-1]
                    * recall[:-1]
                    / np.maximum(precision[:-1] + recall[:-1], 1e-12)
                )
                value = float(scores_f1.max(initial=0.0))
                if value > strongest["f1"]:
                    strongest = {"feature": feature, "scenario": scenario, "f1": value}
    return strongest


def training_eda(frame: pd.DataFrame, raw: pd.DataFrame, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    feature_summary = (
        frame.loc[:, MODEL_FEATURE_COLUMNS].describe().T.reset_index(names="feature")
    )
    feature_summary["missing"] = frame.loc[:, MODEL_FEATURE_COLUMNS].isna().sum().values
    feature_summary["unique"] = frame.loc[:, MODEL_FEATURE_COLUMNS].nunique().values
    correlations = frame.loc[:, MODEL_FEATURE_COLUMNS].corr().stack().reset_index()
    correlations.columns = ["left", "right", "pearson"]
    correlations = correlations.loc[correlations.left < correlations.right]
    scenario_rows = []
    for scenario, group in frame.groupby("scenario_tag", sort=True):
        for feature in MODEL_FEATURE_COLUMNS:
            values = group[feature]
            scenario_rows.append(
                {
                    "scenario_tag": scenario,
                    "feature": feature,
                    "rows": len(group),
                    "mean": float(values.mean()),
                    "median": float(values.median()),
                    "p10": float(values.quantile(0.1)),
                    "p90": float(values.quantile(0.9)),
                }
            )
    scenario_table = pd.DataFrame(scenario_rows)
    rows_per_device = frame.groupby("device_id").size()
    sessions_per_device = raw.groupby("device_id").session_id.nunique()
    single = strongest_single_feature(frame)
    summary = {
        "scope": "training-only; not held-out performance",
        "authorization_rows": len(frame),
        "devices": int(frame.device_id.nunique()),
        "sessions": int(raw.session_id.nunique()),
        "row_class_distribution": frame.label.value_counts().sort_index().to_dict(),
        "device_class_distribution": frame.drop_duplicates("device_id")
        .label.value_counts()
        .sort_index()
        .to_dict(),
        "scenario_device_distribution": frame.drop_duplicates("device_id")
        .scenario_tag.value_counts()
        .sort_index()
        .to_dict(),
        "rows_per_device": rows_per_device.describe().to_dict(),
        "sessions_per_device": sessions_per_device.describe().to_dict(),
        "missing_model_values": int(
            frame.loc[:, MODEL_FEATURE_COLUMNS].isna().sum().sum()
        ),
        "near_constant_features": feature_summary.loc[
            feature_summary.unique <= 1, "feature"
        ].tolist(),
        "strongest_single_feature": single,
        "new_features": list(NEW_FEATURES),
    }
    _write_csv(feature_summary, output / "feature_summary.csv")
    _write_csv(correlations, output / "feature_correlations.csv")
    _write_csv(scenario_table, output / "scenario_feature_distributions.csv")
    atomic_write_json(output / "eda_summary.json", summary)
    return summary


def _candidate_key(row: dict) -> tuple:
    return (
        row["worst_subtype_coverage"],
        row["macro_subtype_coverage"],
        row["pr_auc"],
        -row["brier"],
        -row["cost_rank"],
        1 if row["family"] == "logistic_regression" else 0,
        row["candidate"],
    )


def _runtime() -> dict:
    return {
        "python": sys.version,
        "platform": platform.platform(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "scipy": scipy.__version__,
        "scikit_learn": sklearn.__version__,
        "joblib": joblib.__version__,
    }


def verify_serialization(
    artifact_path: Path, fixture_path: Path, expected_path: Path, tolerance: float
) -> dict:
    command = [
        sys.executable,
        "-c",
        (
            "import json,joblib,pandas as pd; "
            f"a=joblib.load({str(artifact_path)!r}); "
            f"x=pd.read_csv({str(fixture_path)!r}); "
            f"open({str(expected_path)!r},'w').write(json.dumps(a.predict_proba(x).tolist()))"
        ),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(f"separate-process model load failed: {result.stderr}")
    artifact = joblib.load(artifact_path)
    fixture = pd.read_csv(fixture_path)
    local = artifact.predict_proba(fixture)
    separate = np.asarray(json.loads(expected_path.read_text()), dtype=float)
    maximum = float(np.max(np.abs(local - separate), initial=0.0))
    if maximum > tolerance:
        raise RuntimeError("serialization probability parity failed")
    return {
        "rows": len(fixture),
        "maximum_absolute_difference": maximum,
        "tolerance": tolerance,
    }


def run_development_training(
    *, root: Path, config_path: Path, output_dir: Path, log_mlflow: bool = False
) -> dict:
    """Execute training-only Phase 2B work without validation or policy replay."""
    verify_v1_release()
    verify_phase1_protected_inputs()
    verify_training_freeze()
    validate_model_feature_contract()
    config = yaml.safe_load(config_path.read_text())
    seed = int(config["seed"])
    output_dir.mkdir(parents=True, exist_ok=True)
    raw, train_splits = load_training_partition(root)
    frame, parity = generate_training_features(raw, float(config["parity_tolerance"]))
    _write_csv(frame, output_dir / "data/training_features.csv")
    atomic_write_json(output_dir / "metrics/online_batch_parity.json", parity)

    validation_ids = set(
        pd.read_csv(root / "data/v2/development/device_splits.csv").loc[
            lambda data: data.split.eq("validation"), "device_id"
        ]
    )
    folds = make_device_folds(train_splits, int(config["folds"]))
    assert_fold_integrity(folds, set(train_splits.device_id), validation_ids)
    frame = frame.merge(folds, on="device_id", validate="many_to_one")
    _write_csv(folds, output_dir / "training/device_folds.csv")
    eda = training_eda(frame, raw, output_dir / "eda")
    if eda["near_constant_features"]:
        raise RuntimeError(
            f"near-constant Phase 2B features: {eda['near_constant_features']}"
        )
    if eda["strongest_single_feature"]["f1"] > config["single_feature_max_f1"]:
        raise RuntimeError("single-feature shortcut guardrail failed")
    scenario_shortcut = scenario_shortcut_check(frame)
    if scenario_shortcut["f1"] > config["scenario_separator_max_f1"]:
        raise RuntimeError(f"scenario separator guardrail failed: {scenario_shortcut}")

    evaluation_weights = device_evaluation_weights(frame)
    training_weights = balanced_device_training_weights(frame)
    specs = make_candidate_specs(config)
    candidate_rows = []
    fold_rows = []
    runtime_rows = []
    for index, spec in enumerate(specs):
        name = f"{spec['family']}__{index:02d}"
        probability, folds_for_candidate, elapsed = grouped_oof(frame, spec, seed)
        runtime_rows.append({"candidate": name, "training_seconds": elapsed})
        metrics = probability_metrics(frame.label, probability, evaluation_weights)
        threshold, devices = diagnostic_device_threshold(
            frame, probability, float(config["primary_legitimate_intervention_rate"])
        )
        diagnostics = device_diagnostics(devices)
        candidate_rows.append(
            {
                "candidate": name,
                "family": spec["family"],
                "parameters_json": json.dumps(spec["parameters"], sort_keys=True),
                **metrics,
                "diagnostic_threshold": threshold,
                "worst_subtype_coverage": diagnostics["worst_subtype_coverage"],
                "macro_subtype_coverage": diagnostics["macro_subtype_coverage"],
                "cost_rank": 0
                if spec["family"] == "logistic_regression"
                else int(spec["parameters"]["max_iter"]),
                "fold_pr_auc_mean": float(
                    np.mean([row["pr_auc"] for row in folds_for_candidate])
                ),
                "fold_pr_auc_std": float(
                    np.std([row["pr_auc"] for row in folds_for_candidate])
                ),
                "seed": seed,
                "feature_contract_sha256": MODEL_FEATURE_COLUMNS_SHA256,
                "fold_contract_sha256": hashlib.sha256(
                    _csv(folds).encode()
                ).hexdigest(),
            }
        )
        fold_rows.extend({"candidate": name, **row} for row in folds_for_candidate)
    selected_row = max(candidate_rows, key=_candidate_key)
    selected_index = int(selected_row["candidate"].rsplit("__", 1)[1])
    selected_spec = specs[selected_index]
    candidates = pd.DataFrame(candidate_rows).sort_values("candidate")
    _write_csv(candidates, output_dir / "metrics/candidate_oof_metrics.csv")
    _write_csv(
        pd.DataFrame(fold_rows), output_dir / "metrics/candidate_fold_metrics.csv"
    )
    _write_csv(
        pd.DataFrame(runtime_rows),
        output_dir / "metrics/candidate_runtime_diagnostics.csv",
    )

    calibration_rows = []
    calibration_predictions = {}
    calibration_isolation = {}
    reliability_parts = []
    for method in config["calibration_methods"]:
        raw_probability, calibrated, isolation = nested_calibrated_oof(
            frame, selected_spec, method, seed
        )
        calibration_predictions[method] = (raw_probability, calibrated)
        calibration_isolation[method] = isolation
        raw_metrics = probability_metrics(
            frame.label, raw_probability, evaluation_weights
        )
        metrics = probability_metrics(frame.label, calibrated, evaluation_weights)
        calibration_rows.append(
            {
                "method": method,
                "raw_brier": raw_metrics["brier"],
                "brier": metrics["brier"],
                "raw_log_loss": raw_metrics["log_loss"],
                "log_loss": metrics["log_loss"],
                "raw_pr_auc": raw_metrics["pr_auc"],
                "pr_auc": metrics["pr_auc"],
                "ece_10": metrics["ece_10"],
                "maximum_device_overlap": max(
                    row["all_pairwise_device_overlaps"] for row in isolation
                ),
            }
        )
        table = reliability_table(frame.label, calibrated, evaluation_weights)
        table.insert(0, "method", method)
        reliability_parts.append(table)
    calibrations = pd.DataFrame(calibration_rows)
    simplicity = {"none": 0, "sigmoid": 1, "isotonic": 2}
    selected_calibration_row = min(
        calibration_rows,
        key=lambda row: (
            row["brier"],
            row["ece_10"],
            row["log_loss"],
            simplicity[row["method"]],
        ),
    )
    selected_calibration = selected_calibration_row["method"]
    _write_csv(calibrations, output_dir / "metrics/calibration_comparison.csv")
    _write_csv(
        pd.concat(reliability_parts, ignore_index=True),
        output_dir / "metrics/calibration_reliability.csv",
    )

    raw_selected, calibrated_selected = calibration_predictions[selected_calibration]
    predictions = frame[
        [
            "event_id",
            "request_id",
            "device_id",
            "timestamp",
            "label",
            "attack_subtype",
            "scenario_tag",
            "fold",
        ]
    ].copy()
    predictions["raw_probability"] = raw_selected
    predictions["calibrated_probability"] = calibrated_selected
    _write_csv(predictions, output_dir / "predictions/training_oof_predictions.csv")

    device_labels = frame[["device_id", "label"]].drop_duplicates("device_id")
    shuffled = device_labels.label.sample(frac=1, random_state=seed).to_numpy()
    shuffled_map = dict(zip(device_labels.device_id, shuffled, strict=True))
    shuffled_frame = frame.copy()
    shuffled_frame["label"] = shuffled_frame.device_id.map(shuffled_map).astype(int)
    shuffled_probability, _, _ = grouped_oof(shuffled_frame, selected_spec, seed)
    shuffled_auc = float(
        roc_auc_score(
            shuffled_frame.label,
            shuffled_probability,
            sample_weight=device_evaluation_weights(shuffled_frame),
        )
    )
    selected_auc = float(
        probability_metrics(frame.label, calibrated_selected, evaluation_weights)[
            "roc_auc"
        ]
    )
    sanity = {
        "shuffled_label_roc_auc": shuffled_auc,
        "shuffled_label_maximum": config["shuffled_label_max_roc_auc"],
        "strongest_single_feature": eda["strongest_single_feature"],
        "single_feature_maximum": config["single_feature_max_f1"],
        "full_model_roc_auc": selected_auc,
        "full_model_minimum": config["full_model_min_roc_auc"],
        "strongest_new_feature_scenario_separator": scenario_shortcut,
        "scenario_separator_maximum": config["scenario_separator_max_f1"],
    }
    sanity["passed"] = bool(
        shuffled_auc <= config["shuffled_label_max_roc_auc"]
        and selected_auc >= config["full_model_min_roc_auc"]
    )
    if not sanity["passed"]:
        raise RuntimeError(f"training-only sanity checks failed: {sanity}")
    atomic_write_json(output_dir / "metrics/sanity_checks.json", sanity)

    artifact = fit_deployable(frame, selected_spec, selected_calibration, seed)
    model_path = output_dir / "models/selected_model.joblib"
    _atomic_joblib_dump(artifact, model_path)
    fixture = frame.loc[:127, MODEL_FEATURE_COLUMNS]
    fixture_path = output_dir / "models/serialization_fixture.csv"
    expected_path = output_dir / "models/serialization_subprocess_predictions.json"
    _write_csv(fixture, fixture_path)
    serialization = verify_serialization(
        model_path, fixture_path, expected_path, float(config["probability_tolerance"])
    )

    policy_config = yaml.safe_load(
        (root / "configs/v2/phase2b/policy_grid_proposal.yaml").read_text()
    )
    policies = enumerate_policy_grid(policy_config)
    counts = pd.Series([item["family"] for item in policies]).value_counts().to_dict()
    expected_counts = {"rules_only": 8, "ml_only": 25, "combined": 45}
    if len(policies) != 78 or counts != expected_counts:
        raise RuntimeError(
            f"Phase 2B policy grid changed: total={len(policies)} {counts}"
        )
    if len({item["candidate_id"] for item in policies}) != 78:
        raise RuntimeError("Phase 2B policy IDs are not unique")
    policy_payload = {
        "candidate_count": 78,
        "family_counts": expected_counts,
        "candidates": policies,
        "review_block_semantics": policy_config["families"],
        "budgets": yaml.safe_load((root / "configs/v2/policy.yaml").read_text())[
            "budgets"
        ],
        "selection_objective": yaml.safe_load(
            (root / "configs/v2/policy.yaml").read_text()
        )["selection_objective"],
        "enumeration_sha256": hashlib.sha256(
            json.dumps(policies, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "evaluated": False,
    }
    atomic_write_json(output_dir / "policy/policy_search_space.json", policy_payload)

    selection = {
        "selected_candidate": selected_row["candidate"],
        "selected_family": selected_spec["family"],
        "selected_parameters": selected_spec["parameters"],
        "selected_calibration": selected_calibration,
        "ranking_objective": config["ranking_objective"],
        "calibration_objective": config["calibration_objective"],
        "why_selected": _candidate_key(selected_row),
        "candidate_count": len(specs),
        "model_feature_count": len(MODEL_FEATURE_COLUMNS),
        "feature_contract_sha256": MODEL_FEATURE_COLUMNS_SHA256,
    }
    atomic_write_json(output_dir / "metrics/training_selection.json", selection)
    feature_contract = {
        "ordered_features": list(MODEL_FEATURE_COLUMNS),
        "dtypes": {name: "float64" for name in MODEL_FEATURE_COLUMNS},
        "missing_value_policy": (
            "no missing model inputs; explicit availability indicators for "
            "undefined new histories"
        ),
        "feature_contract_sha256": MODEL_FEATURE_COLUMNS_SHA256,
        "feature_engine_version": "v2b-causal-features-1",
        "scoring_moment": "pre-authorization before the current request outcome",
        "removed_features": [],
    }
    atomic_write_json(
        output_dir / "models/model_feature_contract.json", feature_contract
    )
    metadata = {
        **selection,
        "runtime": _runtime(),
        "model_artifact_sha256": sha256_file(model_path),
        "serialization_parity": serialization,
        "fold_device_overlap": 0,
        "oof_rows": len(predictions),
        "oof_complete": bool(predictions.calibrated_probability.notna().all()),
        "training_weight_audit": weight_audit(frame, training_weights),
        "evaluation_weight_audit": weight_audit(frame, evaluation_weights),
        "calibration_isolation": calibration_isolation[selected_calibration],
    }
    atomic_write_json(output_dir / "models/model_metadata.json", metadata)

    if log_mlflow:
        logged_params = {
            "candidate": selected_row["candidate"],
            "family": selected_spec["family"],
            "calibration": selected_calibration,
            "seed": seed,
            "feature_contract_sha256": MODEL_FEATURE_COLUMNS_SHA256,
        }
        logged_metrics = {
            "oof_pr_auc": float(selected_row["pr_auc"]),
            "calibrated_brier": float(selected_calibration_row["brier"]),
            "shuffled_label_roc_auc": shuffled_auc,
        }
        with tempfile.TemporaryDirectory(prefix="mlflow-file-store-") as tracking:
            store = FileStore(tracking)
            experiment_id = store.create_experiment(
                "card-testing-sentinel-v2b-training"
            )
            timestamp = int(time.time() * 1000)
            run = store.create_run(experiment_id, "phase2b", timestamp, [], None)
            for key, value in logged_params.items():
                store.log_param(run.info.run_id, Param(key, str(value)))
            for key, value in logged_metrics.items():
                store.log_metric(run.info.run_id, Metric(key, value, timestamp, 0))
            store.update_run_info(
                run.info.run_id,
                RunStatus.to_string(RunStatus.FINISHED),
                int(time.time() * 1000),
                "completed",
            )
        atomic_write_json(
            output_dir / "metrics/mlflow_training_run.json",
            {
                "experiment": "card-testing-sentinel-v2b-training",
                "tracking_store": "temporary_local_file_store",
                "status": "FINISHED",
                "params": logged_params,
                "metrics": logged_metrics,
            },
        )
    return {
        "selection": selection,
        "parity": parity,
        "sanity": sanity,
        "serialization": serialization,
        "policy_search": policy_payload,
        "runtime": _runtime(),
        "candidate_metrics": candidate_rows,
        "calibration_metrics": calibration_rows,
    }


def compare_reproduction(first: Path, second: Path, tolerance: float) -> dict:
    first_predictions = pd.read_csv(first / "predictions/training_oof_predictions.csv")
    second_predictions = pd.read_csv(
        second / "predictions/training_oof_predictions.csv"
    )
    columns = ["raw_probability", "calibrated_probability"]
    maximum = float(
        np.max(
            np.abs(
                first_predictions[columns].to_numpy()
                - second_predictions[columns].to_numpy()
            ),
            initial=0.0,
        )
    )
    deterministic_files = (
        "training/device_folds.csv",
        "metrics/candidate_oof_metrics.csv",
        "metrics/calibration_comparison.csv",
        "metrics/training_selection.json",
        "models/model_feature_contract.json",
        "policy/policy_search_space.json",
        "eda/eda_summary.json",
    )
    equality = {
        name: (first / name).read_bytes() == (second / name).read_bytes()
        for name in deterministic_files
    }
    if maximum > tolerance or not all(equality.values()):
        raise RuntimeError(
            f"Phase 2B reproduction drift: probability={maximum}, files={equality}"
        )
    return {
        "oof_maximum_absolute_difference": maximum,
        "probability_tolerance": tolerance,
        "deterministic_file_equality": equality,
        "joblib_byte_identity_required": False,
        "selection_identical": True,
        "calibration_identical": True,
    }
