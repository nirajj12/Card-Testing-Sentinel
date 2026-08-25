import io
import json
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import joblib
import mlflow
import numpy as np
import pandas as pd
import sklearn
import yaml
from sklearn.metrics import precision_recall_curve

from card_testing_sentinel.v2.evaluation.access import (
    ROOT,
    sha256_file,
    verify_phase1_protected_inputs,
    verify_v1_release,
)
from card_testing_sentinel.v2.evaluation.calibration import (
    apply_calibrator,
    fit_calibrator,
)
from card_testing_sentinel.v2.evaluation.eda import training_eda
from card_testing_sentinel.v2.evaluation.metrics import (
    probability_metrics,
    reliability_table,
)
from card_testing_sentinel.v2.modeling.artifacts import CalibratedModelArtifact
from card_testing_sentinel.v2.modeling.candidates import (
    build_candidate,
    candidate_specs,
    fit_candidate,
)
from card_testing_sentinel.v2.modeling.features import (
    MODEL_FEATURE_COLUMNS,
    MODEL_FEATURE_COLUMNS_SHA256,
    REMOVED_MODEL_FEATURES,
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
from card_testing_sentinel.v2.policy.rules import MAX_RULE_SCORE, RULES, evaluate_rules


def _diagnostic_threshold(labels, probabilities, weights) -> float:
    precision, recall, thresholds = precision_recall_curve(
        labels, probabilities, sample_weight=weights
    )
    f1 = 2 * precision[:-1] * recall[:-1] / np.maximum(
        precision[:-1] + recall[:-1], 1e-12
    )
    return float(thresholds[int(np.argmax(f1))])


def _training_sequential_diagnostic(frame: pd.DataFrame, probability, rate: float) -> dict:
    scored = frame[["device_id", "label", "attack_subtype", "timestamp"]].copy()
    scored["probability"] = probability
    devices = (
        scored.sort_values("timestamp")
        .groupby("device_id", as_index=False)
        .agg(
            label=("label", "first"),
            attack_subtype=("attack_subtype", "first"),
            maximum_probability=("probability", "max"),
        )
    )
    legitimate = devices.loc[devices.label.eq(0), "maximum_probability"].sort_values(
        ascending=False
    )
    allowance = int(np.floor(len(legitimate) * rate))
    if allowance == 0:
        threshold = 1.0
    else:
        threshold = float(np.nextafter(legitimate.iloc[allowance - 1], np.inf))
    devices["acted"] = devices.maximum_probability >= threshold
    subtypes = {}
    for subtype, group in devices.loc[devices.label.eq(1)].groupby("attack_subtype"):
        subtypes[str(subtype)] = {
            "numerator": int(group.acted.sum()),
            "denominator": int(len(group)),
            "coverage": float(group.acted.mean()),
        }
    values = [row["coverage"] for row in subtypes.values()]
    return {
        "rate": rate,
        "legitimate_allowance": allowance,
        "threshold": threshold,
        "legitimate_interventions": int(
            devices.loc[devices.label.eq(0), "acted"].sum()
        ),
        "subtypes": subtypes,
        "worst_subtype_coverage": min(values),
        "macro_subtype_coverage": float(np.mean(values)),
    }


def generate_oof(
    frame: pd.DataFrame, spec: dict, seed: int
) -> tuple[np.ndarray, list[dict], float, int]:
    probabilities = np.zeros(len(frame), dtype=float)
    fold_rows = []
    last_model = None
    elapsed = 0.0
    for fold in sorted(frame.fold.unique()):
        fit_mask = frame.fold.ne(fold)
        holdout_mask = ~fit_mask
        fit_devices = set(frame.loc[fit_mask, "device_id"])
        holdout_devices = set(frame.loc[holdout_mask, "device_id"])
        if fit_devices & holdout_devices:
            raise RuntimeError("OOF device leakage")
        model = build_candidate(spec["family"], spec["parameters"], seed)
        started = time.perf_counter()
        fit_candidate(
            model,
            spec["family"],
            frame.loc[fit_mask, MODEL_FEATURE_COLUMNS],
            frame.loc[fit_mask, "label"],
            balanced_device_training_weights(frame.loc[fit_mask]),
        )
        probabilities[holdout_mask] = model.predict_proba(
            frame.loc[holdout_mask, MODEL_FEATURE_COLUMNS]
        )[:, 1]
        elapsed += time.perf_counter() - started
        fold_weights = device_evaluation_weights(frame.loc[holdout_mask])
        fold_metric = probability_metrics(
            frame.loc[holdout_mask, "label"],
            probabilities[holdout_mask],
            fold_weights,
        )
        fold_rows.append(
            {
                "fold": int(fold),
                "fit_devices": len(fit_devices),
                "holdout_devices": len(holdout_devices),
                "device_overlap": 0,
                **fold_metric,
            }
        )
        last_model = model
    buffer = io.BytesIO()
    joblib.dump(last_model, buffer)
    return probabilities, fold_rows, elapsed / len(frame), len(buffer.getvalue())


def nested_calibrated_oof(
    frame: pd.DataFrame, spec: dict, method: str, seed: int
) -> tuple[np.ndarray, np.ndarray, list[dict]]:
    raw = np.zeros(len(frame), dtype=float)
    calibrated = np.zeros(len(frame), dtype=float)
    isolation = []
    folds = sorted(frame.fold.unique())
    for outer in folds:
        outer_mask = frame.fold.eq(outer)
        calibration_fold = folds[(folds.index(outer) + 1) % len(folds)]
        calibration_mask = frame.fold.eq(calibration_fold)
        base_mask = ~(outer_mask | calibration_mask)
        base_devices = set(frame.loc[base_mask, "device_id"])
        calibration_devices = set(frame.loc[calibration_mask, "device_id"])
        outer_devices = set(frame.loc[outer_mask, "device_id"])
        if base_devices & calibration_devices or (base_devices | calibration_devices) & outer_devices:
            raise RuntimeError("nested calibration device isolation failed")
        base = build_candidate(spec["family"], spec["parameters"], seed)
        fit_candidate(
            base,
            spec["family"],
            frame.loc[base_mask, MODEL_FEATURE_COLUMNS],
            frame.loc[base_mask, "label"],
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
        calibrated[outer_mask] = apply_calibrator(
            method, calibrator, raw[outer_mask]
        )
        isolation.append(
            {
                "outer_fold": int(outer),
                "base_fit_devices": len(base_devices),
                "calibrator_fit_devices": len(calibration_devices),
                "evaluation_devices": len(outer_devices),
                "all_pairwise_device_overlaps": 0,
            }
        )
    return raw, calibrated, isolation


def fit_deployable_artifact(frame: pd.DataFrame, spec: dict, method: str, seed: int):
    if method == "none":
        base_mask = np.ones(len(frame), dtype=bool)
        calibration_mask = np.zeros(len(frame), dtype=bool)
    else:
        calibration_mask = frame.fold.eq(0).to_numpy()
        base_mask = ~calibration_mask
    base = build_candidate(spec["family"], spec["parameters"], seed)
    fit_candidate(
        base,
        spec["family"],
        frame.loc[base_mask, MODEL_FEATURE_COLUMNS],
        frame.loc[base_mask, "label"],
        balanced_device_training_weights(frame.loc[base_mask]),
    )
    calibrator = None
    if method != "none":
        calibration_raw = base.predict_proba(
            frame.loc[calibration_mask, MODEL_FEATURE_COLUMNS]
        )[:, 1]
        calibrator = fit_calibrator(
            method,
            calibration_raw,
            frame.loc[calibration_mask, "label"].to_numpy(),
            device_evaluation_weights(frame.loc[calibration_mask]),
        )
    return CalibratedModelArtifact(
        base_model=base,
        calibrator=calibrator,
        calibration_method=method,
        family=spec["family"],
        parameters=spec["parameters"],
    )


def _save_reliability_plot(table: pd.DataFrame, path: Path) -> None:
    valid = table.dropna(subset=["mean_probability", "observed_rate"])
    points = " ".join(
        f"{50 + 400 * row.mean_probability:.2f},{450 - 400 * row.observed_rate:.2f}"
        for row in valid.itertuples()
    )
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="520" height="520" viewBox="0 0 520 520">
<rect width="520" height="520" fill="white"/>
<text x="260" y="24" text-anchor="middle" font-family="sans-serif" font-size="16">V2 training-only reliability</text>
<line x1="50" y1="450" x2="450" y2="50" stroke="#888" stroke-dasharray="5 5"/>
<polyline points="{points}" fill="none" stroke="#1769aa" stroke-width="3"/>
<text x="250" y="500" text-anchor="middle" font-family="sans-serif" font-size="13">Mean calibrated probability</text>
<text x="15" y="250" transform="rotate(-90 15 250)" text-anchor="middle" font-family="sans-serif" font-size="13">Observed attack rate</text>
</svg>\n"""
    path.write_text(svg)


def run_training_phase(root: Path = ROOT) -> dict:
    from card_testing_sentinel.v2.evaluation.access import (
        load_training_features,
        load_training_raw_events,
    )

    protected = verify_phase1_protected_inputs()
    v1_hashes = verify_v1_release()
    training_config = yaml.safe_load((root / "configs/v2/training.yaml").read_text())
    seed = int(training_config["seed"])
    splits = pd.read_csv(root / "data/v2/development/device_splits.csv")
    train_splits = splits.loc[splits.split.eq("train")].copy()
    validation_ids = set(splits.loc[splits.split.eq("validation"), "device_id"])
    folds = make_device_folds(train_splits, int(training_config["folds"]))
    assert_fold_integrity(folds, set(train_splits.device_id), validation_ids)
    fold_path = root / "artifacts/v2/training/device_folds.csv"
    folds.to_csv(fold_path, index=False, float_format="%.12g", lineterminator="\n")

    frame = load_training_features().merge(folds, on="device_id", validate="many_to_one")
    raw = load_training_raw_events()
    if not np.isfinite(frame.loc[:, MODEL_FEATURE_COLUMNS].to_numpy()).all():
        raise RuntimeError("nonfinite model feature")
    eda_dir = root / "artifacts/v2/training/eda"
    eda_summary = training_eda(frame, raw, eda_dir)
    (eda_dir / "training_eda_summary.json").write_text(
        json.dumps(eda_summary, indent=2, sort_keys=True) + "\n"
    )
    report_lines = [
        "# V2 training-only EDA",
        "",
        "Validation distributions, labels and performance were not accessed.",
        "",
        f"- Devices: {eda_summary['devices']:,}",
        f"- Precheck rows: {eda_summary['precheck_rows']:,}",
        f"- Lifecycle events: {eda_summary['lifecycle_events']:,}",
        f"- Device-weighted attack prevalence: {eda_summary['device_weighted_positive_rate']:.4f}",
        f"- Row-weighted attack prevalence: {eda_summary['row_weighted_positive_rate']:.4f}",
        "- Removed from model matrix: prior_attempts_10s and prior_attempts_60s because each is extremely correlated with its prospective request counterpart.",
    ]
    (root / "reports/v2/modeling/training_eda.md").write_text("\n".join(report_lines) + "\n")

    evaluation_weights = device_evaluation_weights(frame)
    training_weights = balanced_device_training_weights(frame)
    candidate_rows = []
    prediction_columns = {}
    specs = list(candidate_specs(training_config))
    for index, spec in enumerate(specs):
        name = f"{spec['family']}__{index:02d}"
        probability, fold_metrics, inference_seconds, artifact_bytes = generate_oof(frame, spec, seed)
        threshold = _diagnostic_threshold(frame.label, probability, evaluation_weights)
        metrics = probability_metrics(frame.label, probability, evaluation_weights, threshold)
        diagnostic = _training_sequential_diagnostic(
            frame, probability, training_config["primary_legitimate_intervention_rate"]
        )
        candidate_rows.append(
            {
                "candidate": name,
                "family": spec["family"],
                "parameters_json": json.dumps(spec["parameters"], sort_keys=True),
                **metrics,
                "worst_subtype_coverage": diagnostic["worst_subtype_coverage"],
                "macro_subtype_coverage": diagnostic["macro_subtype_coverage"],
                "diagnostic_threshold": diagnostic["threshold"],
                "legitimate_interventions": diagnostic["legitimate_interventions"],
                "fold_pr_auc_mean": float(np.mean([row["pr_auc"] for row in fold_metrics])),
                "fold_pr_auc_std": float(np.std([row["pr_auc"] for row in fold_metrics])),
                "inference_fit_seconds_per_row": inference_seconds,
                "serialized_bytes": artifact_bytes,
                "folds_json": json.dumps(fold_metrics, sort_keys=True),
                "diagnostic_json": json.dumps(diagnostic, sort_keys=True),
            }
        )
        prediction_columns[name] = probability

    rule_results = [evaluate_rules(row)[0] / MAX_RULE_SCORE for row in frame.loc[:, MODEL_FEATURE_COLUMNS].to_dict("records")]
    rule_threshold = _diagnostic_threshold(frame.label, rule_results, evaluation_weights)
    rule_metrics = probability_metrics(frame.label, rule_results, evaluation_weights, rule_threshold)
    rule_diagnostic = _training_sequential_diagnostic(
        frame, np.asarray(rule_results), training_config["primary_legitimate_intervention_rate"]
    )
    candidate_rows.append(
        {
            "candidate": "rules_baseline",
            "family": "rules",
            "parameters_json": "{}",
            **rule_metrics,
            "worst_subtype_coverage": rule_diagnostic["worst_subtype_coverage"],
            "macro_subtype_coverage": rule_diagnostic["macro_subtype_coverage"],
            "diagnostic_threshold": rule_diagnostic["threshold"],
            "legitimate_interventions": rule_diagnostic["legitimate_interventions"],
            "fold_pr_auc_mean": np.nan,
            "fold_pr_auc_std": np.nan,
            "inference_fit_seconds_per_row": 0.0,
            "serialized_bytes": 0,
            "folds_json": "[]",
            "diagnostic_json": json.dumps(rule_diagnostic, sort_keys=True),
        }
    )
    candidates = pd.DataFrame(candidate_rows)
    candidates.to_csv(root / "artifacts/v2/metrics/candidate_oof_metrics.csv", index=False)
    model_candidates = candidates.loc[candidates.family.ne("rules")].copy()
    family_complexity = {"logistic_regression": 1, "hist_gradient_boosting": 2}
    model_candidates["complexity"] = model_candidates.family.map(family_complexity)
    selected_row = model_candidates.sort_values(
        ["worst_subtype_coverage", "macro_subtype_coverage", "pr_auc", "brier", "inference_fit_seconds_per_row", "complexity", "candidate"],
        ascending=[False, False, False, True, True, True, True],
        kind="mergesort",
    ).iloc[0]
    selected_index = int(selected_row.candidate.rsplit("__", 1)[1])
    selected_spec = specs[selected_index]

    calibration_rows = []
    calibration_predictions = {}
    calibration_isolation = {}
    for method in training_config["calibration_methods"]:
        raw_oof, calibrated_oof, isolation = nested_calibrated_oof(frame, selected_spec, method, seed)
        metric = probability_metrics(frame.label, calibrated_oof, evaluation_weights)
        raw_metric = probability_metrics(frame.label, raw_oof, evaluation_weights)
        calibration_rows.append(
            {"method": method, **metric, "raw_pr_auc": raw_metric["pr_auc"], "pr_auc_degradation": raw_metric["pr_auc"] - metric["pr_auc"]}
        )
        calibration_predictions[method] = (raw_oof, calibrated_oof)
        calibration_isolation[method] = isolation
    calibrations = pd.DataFrame(calibration_rows)
    calibrations.to_csv(root / "artifacts/v2/metrics/calibration_comparison.csv", index=False)
    eligible = calibrations.loc[calibrations.pr_auc_degradation.le(0.005)].copy()
    method_complexity = {"none": 0, "sigmoid": 1, "isotonic": 2}
    eligible["complexity"] = eligible.method.map(method_complexity)
    selected_calibration = str(
        eligible.sort_values(["brier", "ece_10", "log_loss", "complexity", "method"], kind="mergesort").iloc[0].method
    )
    selected_raw_oof, selected_calibrated_oof = calibration_predictions[selected_calibration]
    reliability = reliability_table(frame.label.to_numpy(), selected_calibrated_oof, evaluation_weights)
    reliability.to_csv(root / "artifacts/v2/metrics/training_reliability.csv", index=False)
    _save_reliability_plot(reliability, root / "reports/v2/figures/training_reliability.svg")

    oof = frame[["event_id", "request_id", "device_id", "fold", "label", "attack_subtype", "scenario_tag"]].copy()
    oof["raw_probability"] = selected_raw_oof
    oof["calibrated_probability"] = selected_calibrated_oof
    oof.to_csv(root / "artifacts/v2/predictions/training_oof_predictions.csv", index=False, float_format="%.15g")

    # A second clean execution verifies behavior rather than unstable joblib bytes.
    reproduction_probability, _, _, _ = generate_oof(frame, selected_spec, seed)
    original_probability = prediction_columns[selected_row.candidate]
    if not np.allclose(original_probability, reproduction_probability, rtol=0, atol=training_config["probability_tolerance"]):
        raise RuntimeError("selected OOF probabilities failed clean reproduction")
    reproduction_raw, reproduction_calibrated, _ = nested_calibrated_oof(frame, selected_spec, selected_calibration, seed)
    if not np.allclose(selected_raw_oof, reproduction_raw, rtol=0, atol=training_config["probability_tolerance"]) or not np.allclose(selected_calibrated_oof, reproduction_calibrated, rtol=0, atol=training_config["probability_tolerance"]):
        raise RuntimeError("calibrated OOF probabilities failed clean reproduction")

    artifact = fit_deployable_artifact(frame, selected_spec, selected_calibration, seed)
    model_path = root / "artifacts/v2/models/calibrated_model.joblib"
    joblib.dump(artifact, model_path)
    reloaded = joblib.load(model_path)
    parity_sample = frame.iloc[:100]
    if not np.allclose(artifact.predict_proba(parity_sample), reloaded.predict_proba(parity_sample), rtol=0, atol=training_config["probability_tolerance"]):
        raise RuntimeError("serialized model probability parity failed")

    feature_contract = {
        "model_feature_columns": list(MODEL_FEATURE_COLUMNS),
        "sha256": MODEL_FEATURE_COLUMNS_SHA256,
        "removed": REMOVED_MODEL_FEATURES,
    }
    feature_path = root / "artifacts/v2/models/model_feature_contract.json"
    feature_path.write_text(json.dumps(feature_contract, indent=2, sort_keys=True) + "\n")
    rules_payload = {
        "maximum_score": MAX_RULE_SCORE,
        "rules": [rule.__dict__ for rule in RULES],
        "definitions_frozen_from_training_only": True,
    }
    rules_path = root / "artifacts/v2/policy/rules.json"
    rules_path.write_text(json.dumps(rules_payload, indent=2, sort_keys=True) + "\n")
    metadata = {
        "family": selected_spec["family"],
        "parameters": selected_spec["parameters"],
        "calibration_method": selected_calibration,
        "model_feature_columns_sha256": MODEL_FEATURE_COLUMNS_SHA256,
        "model_artifact_sha256": sha256_file(model_path),
        "calibration_isolation": calibration_isolation[selected_calibration],
        "final_fitting": "base model excludes fold 0 calibrator devices when calibration is used; calibrator sees only predictions for those excluded devices",
    }
    metadata_path = root / "artifacts/v2/models/model_metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")

    frozen_paths = [
        "configs/v2/training.yaml",
        "configs/v2/policy.yaml",
        "src/card_testing_sentinel/v2/modeling/features.py",
        "src/card_testing_sentinel/v2/modeling/weights.py",
        "src/card_testing_sentinel/v2/modeling/folds.py",
        "src/card_testing_sentinel/v2/modeling/candidates.py",
        "src/card_testing_sentinel/v2/modeling/artifacts.py",
        "src/card_testing_sentinel/v2/modeling/training.py",
        "src/card_testing_sentinel/v2/evaluation/metrics.py",
        "src/card_testing_sentinel/v2/evaluation/calibration.py",
        "src/card_testing_sentinel/v2/evaluation/sequential.py",
        "src/card_testing_sentinel/v2/policy/rules.py",
        "src/card_testing_sentinel/v2/policy/selection.py",
        "src/card_testing_sentinel/v2/policy/engine.py",
        "artifacts/v2/training/device_folds.csv",
        "artifacts/v2/models/model_feature_contract.json",
        "artifacts/v2/models/calibrated_model.joblib",
        "artifacts/v2/models/model_metadata.json",
        "artifacts/v2/policy/rules.json",
        "artifacts/v2/predictions/training_oof_predictions.csv",
        "artifacts/v2/metrics/candidate_oof_metrics.csv",
        "artifacts/v2/metrics/calibration_comparison.csv",
        "artifacts/v2/metrics/training_reliability.csv",
    ]
    freeze = {
        "version": "v2-phase2-training-freeze-1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "validation_sealed": True,
        "validation_performance_computed": False,
        "protected_input_hashes": protected,
        "v1_release_entry_hashes": v1_hashes,
        "model_feature_columns": list(MODEL_FEATURE_COLUMNS),
        "model_feature_columns_sha256": MODEL_FEATURE_COLUMNS_SHA256,
        "removed_features": REMOVED_MODEL_FEATURES,
        "fold_file": "artifacts/v2/training/device_folds.csv",
        "fold_file_sha256": sha256_file(fold_path),
        "fold_counts": {str(key): int(value) for key, value in folds.groupby("fold").size().items()},
        "fold_device_overlap": 0,
        "candidate_model_families_and_complete_grids": training_config["candidate_grids"],
        "evaluation_weighting": "each device total=1; each request row=1/request_count_for_device",
        "training_weighting": "each class total=0.5; each device within class equal; device mass divided over its request rows",
        "training_weight_audit": weight_audit(frame, training_weights),
        "evaluation_weight_audit": weight_audit(frame, evaluation_weights),
        "candidate_ranking_objective": training_config["ranking_objective"],
        "selected_base_model": {"candidate": selected_row.candidate, **selected_spec},
        "selected_calibration_method": selected_calibration,
        "calibration_objective": training_config["calibration_objective"],
        "calibration_isolation": calibration_isolation[selected_calibration],
        "rule_definitions": rules_payload,
        "validation_policy_config": yaml.safe_load((root / "configs/v2/policy.yaml").read_text()),
        "metric_definitions": {
            "row_probability_metrics": ["device-weighted PR-AUC", "ROC-AUC", "Brier", "log loss", "10-bin ECE"],
            "device_intervals": "95% Wilson",
            "sequential_denominator": "all devices in the reported class/subtype including never-acted devices",
        },
        "plot_definitions": yaml.safe_load((root / "configs/v2/policy.yaml").read_text())["plots"],
        "seed": seed,
        "runtime": {"python": sys.version, "platform": platform.platform(), "numpy": np.__version__, "pandas": pd.__version__, "scikit_learn": sklearn.__version__, "joblib": joblib.__version__},
        "reproduction": {"probability_absolute_tolerance": training_config["probability_tolerance"], "folds_identical": True, "selection_identical": True, "calibration_identical": True, "oof_probabilities_match": True, "serialization_reload_parity": True},
        "phase2_frozen_artifact_hashes": {name: sha256_file(root / name) for name in frozen_paths},
    }
    freeze_path = root / "artifacts/v2/training/training_freeze.json"
    freeze_path.write_text(json.dumps(freeze, indent=2, sort_keys=True) + "\n")
    freeze_digest = sha256_file(freeze_path)
    (root / "artifacts/v2/training/training_freeze.sha256").write_text(freeze_digest + "\n")
    verify_phase1_protected_inputs()
    verify_v1_release()

    mlflow.set_tracking_uri((root / "mlruns").as_uri())
    mlflow.set_experiment("card-testing-sentinel-v2-training")
    with mlflow.start_run(run_name="training-freeze"):
        mlflow.log_params({"candidate": selected_row.candidate, "family": selected_spec["family"], "calibration": selected_calibration, "seed": seed})
        mlflow.log_metrics({"oof_pr_auc": float(selected_row.pr_auc), "calibrated_brier": float(calibrations.set_index("method").loc[selected_calibration, "brier"])})
        mlflow.log_artifact(str(freeze_path), artifact_path="freeze")
    return {"training_freeze": str(freeze_path), "training_freeze_sha256": freeze_digest, "selected_candidate": selected_row.candidate, "selected_calibration": selected_calibration, "candidate_metrics": candidates.to_dict("records"), "calibration_metrics": calibrations.to_dict("records")}
