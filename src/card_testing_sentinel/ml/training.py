"""Development training: device-grouped CV, candidate selection, calibration.

Selection happens on TRAIN out-of-fold predictions only. The validation split
is not touched here -- it is scored once, afterwards, by
``ml/evaluation.py``, so hyperparameters are never revisited against it.
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn

from card_testing_sentinel.features.specification import (
    FEATURE_CONTRACT_VERSION,
    MODEL_FEATURES,
    MODEL_FEATURES_SHA256,
)
from card_testing_sentinel.ml.calibration import (
    METHODS,
    apply_calibrator,
    fit_calibrator,
)
from card_testing_sentinel.ml.candidates import (
    Candidate,
    build_model,
    candidate_grid,
    fit_model,
    predict,
)
from card_testing_sentinel.ml.folds import assert_fold_integrity, make_device_folds
from card_testing_sentinel.ml.metrics import (
    balanced_training_weights,
    device_weights,
    probability_metrics,
    reliability_bins,
)

#: Columns that exist for grouping and evaluation and must never be fitted on.
NON_FEATURE_COLUMNS = (
    "request_id",
    "device_id",
    "session_id",
    "timestamp",
    "split",
    "label",
    "population",
    "scenario",
    "merchant_id",
    "merchant_kind",
)


@dataclass
class RiskModelArtifact:
    """What the runtime loads: an sklearn estimator, its calibrator, and
    enough identity to refuse to run against the wrong feature contract."""

    model: object
    family: str
    parameters: dict
    calibration_method: str
    calibrator: object | None
    feature_names: tuple[str, ...]
    feature_contract_sha256: str

    def score_frame(self, frame: pd.DataFrame) -> np.ndarray:
        if tuple(frame.columns[: len(self.feature_names)]) != self.feature_names:
            values = frame.loc[:, list(self.feature_names)]
        else:
            values = frame
        raw = np.asarray(
            self.model.predict_proba(
                values
                if self.family == "logistic_regression"
                else values.to_numpy(dtype=float)
            )[:, 1],
            dtype=float,
        )
        return apply_calibrator(self.calibration_method, self.calibrator, raw)

    def score_vector(self, values: np.ndarray) -> float:
        """Score one ordered feature vector -- the runtime's hot path."""
        frame = pd.DataFrame([values], columns=list(self.feature_names))
        return float(self.score_frame(frame)[0])


def assert_feature_contract(frame: pd.DataFrame) -> None:
    """The training table's feature block must equal the runtime contract,
    in order. A silent reorder would train one model and serve another."""
    present = [name for name in frame.columns if name in set(MODEL_FEATURES)]
    if tuple(present) != MODEL_FEATURES:
        raise ValueError(
            "training feature order does not match the runtime feature contract"
        )
    leaked = [name for name in NON_FEATURE_COLUMNS if name in MODEL_FEATURES]
    if leaked:
        raise ValueError(f"grouping columns leaked into the feature contract: {leaked}")


def out_of_fold_scores(
    training: pd.DataFrame, folds: pd.DataFrame, candidate: Candidate, seed: int
) -> np.ndarray:
    assignment = training.device_id.map(folds.set_index("device_id")["fold"])
    scores = np.full(len(training), np.nan)
    for fold in sorted(folds.fold.unique()):
        holdout = assignment.eq(fold).to_numpy()
        fit_rows = training.loc[~holdout]
        model = fit_model(
            build_model(candidate, seed),
            candidate,
            fit_rows,
            fit_rows.label,
            balanced_training_weights(fit_rows),
        )
        scores[holdout] = predict(model, candidate, training.loc[holdout])
    if not np.isfinite(scores).all():
        raise RuntimeError("out-of-fold predictions are incomplete")
    return scores


def train_development_model(
    features_path: Path, config_path: Path, output_dir: Path
) -> dict:
    import yaml

    config = yaml.safe_load(config_path.read_text())
    training_config = config["training"]
    seed = int(training_config["seed"])

    frame = pd.read_csv(features_path)
    assert_feature_contract(frame)
    training = frame.loc[frame.split.eq("train")].reset_index(drop=True)
    validation_devices = set(frame.loc[frame.split.eq("validation"), "device_id"])

    devices = training[["device_id", "scenario"]].drop_duplicates("device_id")
    folds = make_device_folds(devices, int(training_config["folds"]), seed)
    assert_fold_integrity(folds, set(devices.device_id), validation_devices)
    weights = device_weights(training)

    # --- candidate comparison, out-of-fold on TRAIN only -------------------
    candidates = candidate_grid(training_config)
    rows, oof_by_candidate = [], {}
    for candidate in candidates:
        scores = out_of_fold_scores(training, folds, candidate, seed)
        oof_by_candidate[candidate.identifier] = scores
        rows.append(
            {
                "candidate": candidate.identifier,
                "family": candidate.family,
                "parameters": json.dumps(candidate.parameters, sort_keys=True),
                **probability_metrics(training.label, scores, weights),
            }
        )
    comparison = pd.DataFrame(rows).sort_values("pr_auc", ascending=False)
    selected_id = str(comparison.iloc[0].candidate)
    selected = next(c for c in candidates if c.identifier == selected_id)
    selected_scores = oof_by_candidate[selected_id]

    # --- calibration, fitted on out-of-fold TRAIN predictions --------------
    calibration_rows, calibrators = [], {}
    for method in METHODS:
        calibrator = fit_calibrator(
            method, selected_scores, training.label, weights, seed
        )
        calibrated = apply_calibrator(method, calibrator, selected_scores)
        calibrators[method] = calibrator
        calibration_rows.append(
            {
                "method": method,
                **probability_metrics(training.label, calibrated, weights),
            }
        )
    calibration = pd.DataFrame(calibration_rows)
    # Calibration must earn its place: it is only adopted when it improves
    # Brier AND does not materially damage ranking (PR-AUC).
    raw = calibration.loc[calibration.method.eq("none")].iloc[0]
    eligible = calibration.loc[
        (calibration.brier <= raw.brier)
        & (
            calibration.pr_auc
            >= raw.pr_auc - float(training_config["pr_auc_tolerance"])
        )
    ]
    calibration_method = str(eligible.sort_values("brier").iloc[0].method)

    # --- final fit on all of TRAIN ----------------------------------------
    model = fit_model(
        build_model(selected, seed),
        selected,
        training,
        training.label,
        balanced_training_weights(training),
    )
    artifact = RiskModelArtifact(
        model=model,
        family=selected.family,
        parameters=dict(selected.parameters),
        calibration_method=calibration_method,
        calibrator=calibrators[calibration_method],
        feature_names=MODEL_FEATURES,
        feature_contract_sha256=MODEL_FEATURES_SHA256,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, output_dir / "risk_model.joblib")
    comparison.to_csv(output_dir / "model_comparison.csv", index=False)
    calibration.to_csv(output_dir / "calibration_comparison.csv", index=False)
    folds.to_csv(output_dir / "device_folds.csv", index=False)
    pd.DataFrame(
        reliability_bins(
            training.label,
            apply_calibrator(
                calibration_method, calibrators[calibration_method], selected_scores
            ),
            weights,
        )
    ).to_csv(output_dir / "calibration_bins.csv", index=False)

    manifest = json.loads((features_path.parent / "manifest.json").read_text())
    metadata = {
        "status": "development_frozen_candidate",
        "final": False,
        "selected_candidate": selected_id,
        "family": selected.family,
        "parameters": selected.parameters,
        "selected_calibration": calibration_method,
        "calibration_rule": (
            "adopted only if it improves device-weighted Brier without losing "
            f"more than {training_config['pr_auc_tolerance']} PR-AUC"
        ),
        "selection_metric": "device-weighted PR-AUC on train out-of-fold",
        "folds": int(training_config["folds"]),
        "seed": seed,
        "training_devices": int(training.device_id.nunique()),
        "training_rows": int(len(training)),
        "validation_devices": len(validation_devices),
        "feature_contract_version": FEATURE_CONTRACT_VERSION,
        "feature_contract_sha256": MODEL_FEATURES_SHA256,
        "feature_count": len(MODEL_FEATURES),
        "training_config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
        "dataset_config_sha256": manifest["config_sha256"],
        "dataset_generator_version": manifest["generator_version"],
        "cross_validation": comparison.to_dict("records"),
        "calibration_comparison": calibration.to_dict("records"),
        "runtime": {
            "python": sys.version.split()[0],
            "scikit_learn": sklearn.__version__,
            "numpy": np.__version__,
            "joblib": joblib.__version__,
            "platform": platform.system(),
        },
        "created_utc": datetime.now(UTC).isoformat(),
        "blind_evaluated": False,
    }
    (output_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True, default=str) + "\n"
    )
    (output_dir / "feature_contract.json").write_text(
        json.dumps(
            {
                "version": FEATURE_CONTRACT_VERSION,
                "feature_contract_sha256": MODEL_FEATURES_SHA256,
                "ordered_features": list(MODEL_FEATURES),
                "scoring_moment": (
                    "pre-authorization, before the current outcome exists"
                ),
            },
            indent=2,
        )
        + "\n"
    )
    return metadata


def feature_importance(
    artifact: RiskModelArtifact, frame: pd.DataFrame
) -> pd.DataFrame:
    """Coefficients for logistic regression, permutation importance otherwise."""
    if artifact.family == "logistic_regression":
        classifier = artifact.model.named_steps["classifier"]
        coefficients = np.asarray(classifier.coef_[0], dtype=float)
        return (
            pd.DataFrame(
                {
                    "feature": list(artifact.feature_names),
                    "coefficient": coefficients,
                    "direction": np.where(
                        coefficients >= 0, "raises_risk", "lowers_risk"
                    ),
                    "absolute_importance": np.abs(coefficients),
                }
            )
            .sort_values("absolute_importance", ascending=False)
            .reset_index(drop=True)
        )
    from sklearn.inspection import permutation_importance

    result = permutation_importance(
        artifact.model,
        frame.loc[:, list(artifact.feature_names)].to_numpy(dtype=float),
        frame.label.to_numpy(dtype=int),
        n_repeats=5,
        random_state=0,
        scoring="average_precision",
    )
    return (
        pd.DataFrame(
            {
                "feature": list(artifact.feature_names),
                "coefficient": result.importances_mean,
                "direction": "permutation",
                "absolute_importance": np.abs(result.importances_mean),
            }
        )
        .sort_values("absolute_importance", ascending=False)
        .reset_index(drop=True)
    )


def artifact_dict(artifact: RiskModelArtifact) -> dict:
    return {
        key: value
        for key, value in asdict(artifact).items()
        if key not in ("model", "calibrator")
    }
