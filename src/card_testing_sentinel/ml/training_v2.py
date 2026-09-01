"""Model v2 development training: grouped CV, selection, calibration, ablation.

Selection happens on TRAIN out-of-fold predictions only. The validation split
is not read here at all -- it is scored once, afterwards, so hyperparameters
are never revisited against it.

Model v1 and its artifacts are untouched: v2 writes to its own directory
under its own contract hash.
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
import yaml

from card_testing_sentinel.features.specification_v2 import (
    FEATURE_CONTRACT_V2_VERSION,
    MODEL_FEATURES_V2,
    MODEL_FEATURES_V2_SHA256,
)
from card_testing_sentinel.ml.calibration import (
    METHODS,
    apply_calibrator,
    fit_calibrator,
)
from card_testing_sentinel.ml.candidates_v2 import (
    CandidateV2,
    build_model_v2,
    candidate_grid_v2,
    fit_model_v2,
    fitted_feature_names,
    predict_v2,
)
from card_testing_sentinel.ml.folds_v2 import (
    assert_fold_integrity,
    make_grouped_folds,
)
from card_testing_sentinel.ml.metrics import (
    balanced_training_weights,
    device_weights,
    probability_metrics,
    reliability_bins,
)

#: Present for grouping and evaluation; never fitted on.
NON_FEATURE_COLUMNS = (
    "request_id",
    "device_id",
    "customer_id",
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
class RiskModelArtifactV2:
    """What a v2 runtime would load: an estimator, its calibrator, and enough
    identity to refuse to run against the wrong feature contract."""

    model: object
    family: str
    parameters: dict
    calibration_method: str
    calibrator: object | None
    feature_names: tuple[str, ...]
    feature_contract_sha256: str
    feature_contract_version: str
    interactions: tuple[tuple[str, str], ...] = ()

    def score_frame(self, frame: pd.DataFrame) -> np.ndarray:
        values = frame.loc[:, list(self.feature_names)]
        raw = np.asarray(
            self.model.predict_proba(
                values
                if self.family.startswith("logistic")
                else values.to_numpy(dtype=float)
            )[:, 1],
            dtype=float,
        )
        return apply_calibrator(self.calibration_method, self.calibrator, raw)

    def score_vector(self, values: np.ndarray) -> float:
        frame = pd.DataFrame([values], columns=list(self.feature_names))
        return float(self.score_frame(frame)[0])


def assert_feature_contract_v2(frame: pd.DataFrame) -> None:
    present = [name for name in frame.columns if name in set(MODEL_FEATURES_V2)]
    if tuple(present) != MODEL_FEATURES_V2:
        raise ValueError("training feature order does not match contract v2")
    leaked = [name for name in NON_FEATURE_COLUMNS if name in MODEL_FEATURES_V2]
    if leaked:
        raise ValueError(f"grouping columns leaked into the contract: {leaked}")


def out_of_fold_scores(
    training: pd.DataFrame,
    folds: pd.DataFrame,
    candidate: CandidateV2,
    seed: int,
) -> np.ndarray:
    assignment = training.device_id.map(folds.set_index("device_id")["fold"])
    scores = np.full(len(training), np.nan)
    for fold in sorted(folds.fold.unique()):
        holdout = assignment.eq(fold).to_numpy()
        fit_rows = training.loc[~holdout]
        model = fit_model_v2(
            build_model_v2(candidate, seed),
            candidate,
            fit_rows,
            fit_rows.label,
            balanced_training_weights(fit_rows),
        )
        scores[holdout] = predict_v2(model, candidate, training.loc[holdout])
    if not np.isfinite(scores).all():
        raise RuntimeError("out-of-fold predictions are incomplete")
    return scores


def coefficient_table(model, candidate: CandidateV2) -> pd.DataFrame:
    """Standardised coefficients, largest magnitude first."""
    classifier = model.named_steps["classifier"]
    names = fitted_feature_names(candidate)
    coefficients = np.asarray(classifier.coef_[0], dtype=float)
    return (
        pd.DataFrame(
            {
                "feature": names,
                "coefficient": coefficients,
                "direction": np.where(coefficients >= 0, "raises_risk", "lowers_risk"),
                "absolute": np.abs(coefficients),
            }
        )
        .sort_values("absolute", ascending=False)
        .reset_index(drop=True)
    )


def coefficient_stability(
    training: pd.DataFrame, folds: pd.DataFrame, candidate: CandidateV2, seed: int
) -> pd.DataFrame:
    """Per-fold coefficients, so sign flips are visible rather than averaged.

    Model v1 showed correlated features taking opposite signs; that is only
    detectable by refitting and looking.
    """
    assignment = training.device_id.map(folds.set_index("device_id")["fold"])
    rows: list[pd.Series] = []
    for fold in sorted(folds.fold.unique()):
        fit_rows = training.loc[~assignment.eq(fold).to_numpy()]
        model = fit_model_v2(
            build_model_v2(candidate, seed),
            candidate,
            fit_rows,
            fit_rows.label,
            balanced_training_weights(fit_rows),
        )
        table = coefficient_table(model, candidate).set_index("feature").coefficient
        rows.append(table.rename(f"fold_{fold}"))
    matrix = pd.concat(rows, axis=1)
    summary = pd.DataFrame(
        {
            "mean": matrix.mean(axis=1).round(4),
            "std": matrix.std(axis=1).round(4),
            "min": matrix.min(axis=1).round(4),
            "max": matrix.max(axis=1).round(4),
        }
    )
    summary["sign_flips"] = (
        (matrix > 0).sum(axis=1).clip(upper=1)
        + (matrix < 0).sum(axis=1).clip(upper=1)
        - 1
    )
    return summary.reset_index().sort_values(
        ["sign_flips", "std"], ascending=[False, False]
    )


def run_ablations(
    training: pd.DataFrame,
    folds: pd.DataFrame,
    candidate: CandidateV2,
    seed: int,
    ablations: dict,
    reference_flag_rate: float,
) -> pd.DataFrame:
    """Refit the SELECTED configuration on feature subsets.

    Device-level recall and false-positive rate are compared at a matched
    flag rate, not at a fixed threshold: a smaller feature set shifts the
    score distribution, and comparing at a fixed cut would measure that shift
    instead of the information loss.
    """
    from card_testing_sentinel.ml.evaluation import device_outcomes, device_summary

    rows = []
    for name, removed in ablations.items():
        kept = tuple(
            feature for feature in candidate.features if feature not in set(removed)
        )
        subset = candidate.with_features(kept, name)
        scores = out_of_fold_scores(training, folds, subset, seed)
        weights = device_weights(training)
        metrics = probability_metrics(
            training.label.to_numpy(dtype=int), scores, weights
        )
        threshold = float(np.quantile(scores, 1.0 - reference_flag_rate))
        flagged = scores >= threshold
        summary = device_summary(device_outcomes(training, flagged))
        rows.append(
            {
                "feature_set": name,
                "features": len(kept),
                "removed": len(removed),
                "pr_auc": round(metrics["pr_auc"], 4),
                "roc_auc": round(metrics["roc_auc"], 4),
                "brier": round(metrics["brier"], 4),
                "matched_flag_rate": round(reference_flag_rate, 4),
                "matched_threshold": round(threshold, 4),
                "attack_device_recall": summary["attack_device_recall"],
                "legitimate_device_fpr": summary["legitimate_device_fpr"],
            }
        )
    return pd.DataFrame(rows)


def train_model_v2(features_path: Path, config_path: Path, output_dir: Path) -> dict:
    config = yaml.safe_load(config_path.read_text())
    training_config = config["training"]
    seed = int(training_config["seed"])

    frame = pd.read_csv(features_path)
    assert_feature_contract_v2(frame)
    training = frame.loc[frame.split.eq("train")].reset_index(drop=True)
    if training.empty:
        raise RuntimeError("training split is empty")

    grouping = [
        name
        for name in ("device_id", "customer_id", "scenario")
        if name in training.columns
    ]
    devices = training.drop_duplicates("device_id").loc[:, grouping]
    folds = make_grouped_folds(devices, int(training_config["folds"]), seed)
    assert_fold_integrity(folds, int(training_config["folds"]))

    labels = training.label.to_numpy(dtype=int)
    weights = device_weights(training)

    # --- candidate selection, out-of-fold on TRAIN only --------------------
    candidates = candidate_grid_v2(config)
    scored: dict[str, np.ndarray] = {}
    rows = []
    for candidate in candidates:
        scores = out_of_fold_scores(training, folds, candidate, seed)
        scored[candidate.identifier] = scores
        metrics = probability_metrics(labels, scores, weights)
        rows.append(
            {
                "candidate": candidate.identifier,
                "family": candidate.family,
                "parameters": json.dumps(candidate.parameters, sort_keys=True),
                **{k: round(v, 6) for k, v in metrics.items()},
            }
        )
    comparison = pd.DataFrame(rows).sort_values("pr_auc", ascending=False)
    chosen_id = str(comparison.iloc[0].candidate)
    chosen = next(c for c in candidates if c.identifier == chosen_id)
    chosen_scores = scored[chosen_id]

    # --- calibration, fitted on out-of-fold TRAIN predictions --------------
    calibration_rows, calibrators = [], {}
    for method in METHODS:
        calibrator = fit_calibrator(method, chosen_scores, labels, weights, seed)
        calibrated = apply_calibrator(method, calibrator, chosen_scores)
        calibrators[method] = calibrator
        calibration_rows.append(
            {"method": method, **probability_metrics(labels, calibrated, weights)}
        )
    calibration = pd.DataFrame(calibration_rows)
    raw = calibration.loc[calibration.method.eq("none")].iloc[0]
    tolerance = float(training_config["pr_auc_tolerance"])
    eligible = calibration.loc[
        (calibration.brier <= raw.brier)
        & (calibration.pr_auc >= raw.pr_auc - tolerance)
    ]
    calibration_method = str(eligible.sort_values("brier").iloc[0].method)

    # --- ablations on the selected configuration ---------------------------
    reporting_threshold = float(config["evaluation"]["reporting_threshold"])
    calibrated_train = apply_calibrator(
        calibration_method, calibrators[calibration_method], chosen_scores
    )
    reference_flag_rate = float((calibrated_train >= reporting_threshold).mean())
    ablations = run_ablations(
        training,
        folds,
        chosen,
        seed,
        config["ablations"],
        reference_flag_rate,
    )

    # --- fit the final model on all of TRAIN -------------------------------
    final_model = fit_model_v2(
        build_model_v2(chosen, seed),
        chosen,
        training,
        training.label,
        balanced_training_weights(training),
    )
    artifact = RiskModelArtifactV2(
        model=final_model,
        family=chosen.family,
        parameters=dict(chosen.parameters),
        calibration_method=calibration_method,
        calibrator=calibrators[calibration_method],
        feature_names=tuple(chosen.features),
        feature_contract_sha256=MODEL_FEATURES_V2_SHA256,
        feature_contract_version=FEATURE_CONTRACT_V2_VERSION,
        interactions=tuple(chosen.interactions),
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, output_dir / "risk_model_v2.joblib")

    reports = output_dir.parent / "evaluation"
    reports.mkdir(parents=True, exist_ok=True)
    comparison.to_csv(reports / "model_v2_comparison.csv", index=False)
    calibration.to_csv(reports / "model_v2_calibration.csv", index=False)
    ablations.to_csv(reports / "model_v2_ablations.csv", index=False)

    stability = pd.DataFrame()
    coefficients = pd.DataFrame()
    if chosen.family.startswith("logistic"):
        coefficients = coefficient_table(final_model, chosen)
        coefficients.to_csv(reports / "model_v2_coefficients.csv", index=False)
        stability = coefficient_stability(training, folds, chosen, seed)
        stability.to_csv(reports / "model_v2_coefficient_stability.csv", index=False)

    metadata = {
        "model_version": config["model_version"],
        "status": "development_candidate_v2",
        "selected_candidate": chosen_id,
        "selected_family": chosen.family,
        "selected_parameters": dict(chosen.parameters),
        "selected_calibration": calibration_method,
        "calibration_rule": (
            "adopted only if it improves Brier without costing more than "
            f"{tolerance} device-weighted PR-AUC"
        ),
        "feature_contract_version": FEATURE_CONTRACT_V2_VERSION,
        "feature_contract_sha256": MODEL_FEATURES_V2_SHA256,
        "feature_count": len(chosen.features),
        "interactions": [list(pair) for pair in chosen.interactions],
        "training_seed": seed,
        "folds": int(training_config["folds"]),
        "group_by": training_config["group_by"],
        "training_rows": int(len(training)),
        "training_devices": int(training.device_id.nunique()),
        "training_groups": int(folds.group_id.nunique()),
        "training_config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
        "features_sha256": hashlib.sha256(features_path.read_bytes()).hexdigest(),
        "model_sha256": hashlib.sha256(
            (output_dir / "risk_model_v2.joblib").read_bytes()
        ).hexdigest(),
        "out_of_fold_scores": {
            k: round(v, 6)
            for k, v in probability_metrics(labels, calibrated_train, weights).items()
        },
        "calibration_bins": reliability_bins(labels, calibrated_train, weights),
        "reference_flag_rate": round(reference_flag_rate, 4),
        "environment": {
            "python": sys.version.split()[0],
            "sklearn": sklearn.__version__,
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "platform": platform.platform(),
        },
        "created_utc": datetime.now(UTC).isoformat(),
        "validation_scored": False,
        "blind_evaluated": False,
        "note": (
            "Selected on TRAIN out-of-fold predictions only. The validation "
            "split was not read during selection or calibration."
        ),
    }
    (output_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True, default=str) + "\n"
    )
    (output_dir / "feature_contract.json").write_text(
        json.dumps(
            {
                "feature_contract_version": FEATURE_CONTRACT_V2_VERSION,
                "feature_contract_sha256": MODEL_FEATURES_V2_SHA256,
                "features": list(MODEL_FEATURES_V2),
                "model_features": list(chosen.features),
            },
            indent=2,
        )
        + "\n"
    )
    return {
        "metadata": metadata,
        "comparison": comparison,
        "calibration": calibration,
        "ablations": ablations,
        "coefficients": coefficients,
        "stability": stability,
    }
