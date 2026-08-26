"""Device-grouped development training and calibration pipeline."""

from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import yaml

from card_testing_sentinel.common.io import atomic_write_json
from card_testing_sentinel.features.specification import (
    MODEL_FEATURES,
    MODEL_FEATURES_SHA256,
)
from card_testing_sentinel.ml.calibration import apply_calibrator, fit_calibrator
from card_testing_sentinel.ml.candidates import (
    build_candidate,
    candidate_specs,
    fit_candidate,
)
from card_testing_sentinel.ml.folds import assert_fold_integrity, make_device_folds
from card_testing_sentinel.ml.metrics import probability_metrics
from card_testing_sentinel.ml.weights import (
    balanced_device_training_weights,
    device_evaluation_weights,
)
from card_testing_sentinel.modeling.artifacts import CalibratedRiskModelArtifact


def _predict(model, frame: pd.DataFrame) -> np.ndarray:
    values = frame.loc[:, MODEL_FEATURES]
    return np.asarray(model.predict_proba(values)[:, 1], dtype=float)


def _out_of_fold_predictions(
    frame: pd.DataFrame, folds: pd.DataFrame, spec: dict, seed: int
) -> np.ndarray:
    assignments = frame.device_id.map(folds.set_index("device_id")["fold"])
    predictions = np.full(len(frame), np.nan)
    for fold in sorted(folds.fold.unique()):
        holdout = assignments.eq(fold)
        fit = ~holdout
        model = build_candidate(spec["family"], spec["parameters"], seed)
        fit_candidate(
            model,
            spec["family"],
            frame.loc[fit, MODEL_FEATURES],
            frame.loc[fit, "label"],
            balanced_device_training_weights(frame.loc[fit]),
        )
        predictions[holdout] = _predict(model, frame.loc[holdout])
    if not np.isfinite(predictions).all():
        raise RuntimeError("out-of-fold predictions are incomplete")
    return predictions


def train_development_model(
    feature_path: Path, config_path: Path, output_dir: Path
) -> dict:
    """Train development candidates without reading saved blind evidence."""
    config = yaml.safe_load(config_path.read_text())
    frame = pd.read_csv(feature_path)
    training = frame.loc[frame.split.eq("train")].reset_index(drop=True)
    validation_ids = set(frame.loc[frame.split.eq("validation"), "device_id"])
    device_contract = training[["device_id", "scenario_tag", "split"]].drop_duplicates()
    folds = make_device_folds(device_contract, int(config["folds"]))
    assert_fold_integrity(folds, set(device_contract.device_id), validation_ids)
    weights = device_evaluation_weights(training)

    candidate_rows = []
    predictions_by_candidate: dict[int, np.ndarray] = {}
    specs = list(candidate_specs(config))
    for index, spec in enumerate(specs):
        predictions = _out_of_fold_predictions(
            training, folds, spec, int(config["seed"])
        )
        predictions_by_candidate[index] = predictions
        candidate_rows.append(
            {
                "candidate_index": index,
                "family": spec["family"],
                "parameters": str(spec["parameters"]),
                **probability_metrics(training.label, predictions, weights),
            }
        )
    candidate_table = pd.DataFrame(candidate_rows)
    selected_index = int(candidate_table.sort_values("pr_auc").iloc[-1].candidate_index)
    selected_spec = specs[selected_index]
    raw_oof = predictions_by_candidate[selected_index]

    calibration_rows = []
    calibrators = {}
    for method in config["calibration_methods"]:
        calibrator = fit_calibrator(method, raw_oof, training.label, weights)
        calibrated = apply_calibrator(method, calibrator, raw_oof)
        calibrators[method] = calibrator
        calibration_rows.append(
            {
                "method": method,
                **probability_metrics(training.label, calibrated, weights),
            }
        )
    calibration_table = pd.DataFrame(calibration_rows)
    selected_method = str(calibration_table.sort_values("brier").iloc[0].method)

    model = build_candidate(
        selected_spec["family"], selected_spec["parameters"], int(config["seed"])
    )
    fit_candidate(
        model,
        selected_spec["family"],
        training.loc[:, MODEL_FEATURES],
        training.label,
        balanced_device_training_weights(training),
    )
    artifact = CalibratedRiskModelArtifact(
        base_model=model,
        calibrator=calibrators[selected_method],
        calibration_method=selected_method,
        family=selected_spec["family"],
        parameters=selected_spec["parameters"],
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, output_dir / "development_model.joblib")
    candidate_table.to_csv(output_dir / "candidate_metrics.csv", index=False)
    calibration_table.to_csv(output_dir / "calibration_metrics.csv", index=False)
    folds.to_csv(output_dir / "device_folds.csv", index=False)
    summary = {
        "status": "development_training_completed",
        "selected_candidate": selected_spec,
        "selected_calibration": selected_method,
        "feature_count": len(MODEL_FEATURES),
        "feature_contract_sha256": MODEL_FEATURES_SHA256,
        "training_devices": int(training.device_id.nunique()),
        "training_rows": int(len(training)),
        "blind_evidence_read": False,
    }
    atomic_write_json(output_dir / "training_summary.json", summary)
    return summary
