"""Evaluate the selected development model on the VALIDATION split.

    python pipelines/evaluate_model.py

Produces the baseline comparison, threshold sweep, per-scenario and
per-merchant breakdowns, feature importance and the ablation study. No blind
data is read or generated.
"""

import json
import shutil
from pathlib import Path

import joblib
import pandas as pd
import yaml

from card_testing_sentinel.features.specification import MODEL_FEATURES
from card_testing_sentinel.ml.candidates import Candidate
from card_testing_sentinel.ml.evaluation import (
    CARD_HISTORY_FEATURES,
    HISTORY_FEATURES,
    VELOCITY_FEATURES,
    baseline_comparison,
    device_outcomes,
    device_summary,
    merchant_metrics,
    risk_by_scenario,
    rule_scores,
    run_ablation,
    scenario_metrics,
    threshold_sweep,
)
from card_testing_sentinel.ml.metrics import (
    device_weights,
    probability_metrics,
    reliability_bins,
)
from card_testing_sentinel.ml.training import feature_importance

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/generated/development"
MODEL_DIR = ROOT / "artifacts/model"
OUT = ROOT / "artifacts/evaluation"

if __name__ == "__main__":
    config = yaml.safe_load((ROOT / "configs/training.yaml").read_text())
    evaluation_config = config["evaluation"]
    threshold = float(evaluation_config["reporting_threshold"])
    metadata = json.loads((MODEL_DIR / "metadata.json").read_text())
    artifact = joblib.load(MODEL_DIR / "risk_model.joblib")

    frame = pd.read_csv(DATA / "features.csv")
    training = frame.loc[frame.split.eq("train")].reset_index(drop=True)
    validation = frame.loc[frame.split.eq("validation")].reset_index(drop=True)

    risk = artifact.score_frame(validation.loc[:, list(MODEL_FEATURES)])
    rules = rule_scores(validation)
    weights = device_weights(validation)
    OUT.mkdir(parents=True, exist_ok=True)

    baselines = baseline_comparison(validation, risk, rules, evaluation_config)
    baselines.to_csv(OUT / "baseline_comparison.csv", index=False)
    threshold_sweep(validation, risk).to_csv(OUT / "threshold_sweep.csv", index=False)

    flagged = risk >= threshold
    scenario_metrics(validation, flagged).to_csv(OUT / "scenario_metrics.csv")
    merchant_metrics(validation, flagged).to_csv(
        OUT / "merchant_metrics.csv", index=False
    )
    risk_by_scenario(validation, risk).to_csv(OUT / "risk_by_scenario.csv", index=False)
    feature_importance(artifact, validation).to_csv(
        OUT / "feature_importance.csv", index=False
    )

    candidate = Candidate(
        metadata["selected_candidate"], metadata["family"], metadata["parameters"]
    )
    # Ablation rows are compared at the reference model's flag rate, not at a
    # fixed score, because each refit is uncalibrated on its own scale.
    run_ablation(
        training,
        validation,
        candidate,
        int(config["training"]["seed"]),
        {
            "all_features": MODEL_FEATURES,
            "minus_card_history": tuple(
                n for n in MODEL_FEATURES if n not in CARD_HISTORY_FEATURES
            ),
            "velocity_only": VELOCITY_FEATURES,
            "history_only": HISTORY_FEATURES,
        },
        float((risk >= threshold).mean()),
    ).to_csv(OUT / "ablation_results.csv", index=False)

    # copy, never move: this pipeline must stay re-runnable
    for name in ("model_comparison.csv", "calibration_comparison.csv"):
        shutil.copyfile(MODEL_DIR / name, OUT / name)
    development = {
        "status": "development_validation_only",
        "blind_evaluated": False,
        "selected_candidate": metadata["selected_candidate"],
        "selected_calibration": metadata["selected_calibration"],
        "reporting_threshold": threshold,
        "reporting_threshold_note": (
            "provisional, used only to make the per-group tables comparable; "
            "operating points are chosen in the policy phase"
        ),
        "prevalence_note": (
            "benchmark prevalence is enriched; precision figures are labelled "
            "benchmark_precision and are not production estimates"
        ),
        "validation_rows": int(len(validation)),
        "validation_devices": int(validation.device_id.nunique()),
        "model_scores": probability_metrics(validation.label, risk, weights),
        "calibration_bins": reliability_bins(validation.label, risk, weights),
        "device_level_at_reporting_threshold": device_summary(
            device_outcomes(validation, flagged)
        ),
        "feature_contract_sha256": metadata["feature_contract_sha256"],
        "dataset_config_sha256": metadata["dataset_config_sha256"],
    }
    (OUT / "development_metrics.json").write_text(
        json.dumps(development, indent=2, sort_keys=True, default=str) + "\n"
    )
    print(
        json.dumps(
            {k: v for k, v in development.items() if k != "calibration_bins"},
            indent=2,
            sort_keys=True,
            default=str,
        )
    )
