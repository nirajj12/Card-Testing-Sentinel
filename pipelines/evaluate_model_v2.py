"""Score Model v2 once on the untouched Dataset v3 validation split.

    python pipelines/evaluate_model_v2.py

The candidate, its hyperparameters and its calibration were frozen from train
cross-validation before this ran. Nothing here is tuned, and no policy
threshold is selected.

Also fits ONE decomposition aid: the same configuration restricted to the
v1-equivalent feature families, so the dataset effect and the feature effect
can be separated. That configuration is fixed, not searched.
"""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import joblib
import pandas as pd
import yaml

from card_testing_sentinel.ml.candidates_v2 import (
    CandidateV2,
    build_model_v2,
    fit_model_v2,
    predict_v2,
)
from card_testing_sentinel.ml.evaluation_v2 import (
    baseline_table,
    matched_fpr_comparison,
    rule_scores_v2,
    scenario_table,
    segment_table,
    threshold_table,
)
from card_testing_sentinel.ml.metrics import (
    balanced_training_weights,
    device_weights,
    probability_metrics,
    reliability_bins,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/generated/development_v3/features_v2.csv"
MODEL_DIR = ROOT / "artifacts/model_v2"
OUT = ROOT / "artifacts/evaluation"

if __name__ == "__main__":
    config = yaml.safe_load((ROOT / "configs/training_v2.yaml").read_text())
    evaluation = config["evaluation"]
    metadata = json.loads((MODEL_DIR / "metadata.json").read_text())
    artifact = joblib.load(MODEL_DIR / "risk_model_v2.joblib")

    frame = pd.read_csv(DATA)
    train = frame.loc[frame.split.eq("train")].reset_index(drop=True)
    validation = frame.loc[frame.split.eq("validation")].reset_index(drop=True)
    if validation.empty:
        raise RuntimeError("validation split is empty")

    risk = artifact.score_frame(validation)
    rules = rule_scores_v2(validation)
    weights = device_weights(validation)
    labels = validation.label.to_numpy(dtype=int)

    model_metrics = probability_metrics(labels, risk, weights)
    thresholds = evaluation["score_thresholds"]
    reporting = float(evaluation["reporting_threshold"])

    table = threshold_table(validation, risk, thresholds)
    baselines = baseline_table(validation, risk, rules, evaluation)
    matched = matched_fpr_comparison(baselines)
    scenarios = scenario_table(validation, risk, reporting)
    segments = segment_table(validation, risk, thresholds)

    # --- decomposition aid: the same configuration, v1-equivalent features --
    v1_like = CandidateV2(
        identifier="v1_equivalent_on_dataset_v3",
        family=artifact.family,
        parameters=dict(artifact.parameters),
        features=tuple(
            name
            for name in artifact.feature_names
            if name not in set(config["ablations"]["v1_equivalent_families"])
        ),
    )
    v1_model = fit_model_v2(
        build_model_v2(v1_like, int(metadata["training_seed"])),
        v1_like,
        train,
        train.label,
        balanced_training_weights(train),
    )
    v1_like_risk = predict_v2(v1_model, v1_like, validation)
    v1_like_metrics = probability_metrics(labels, v1_like_risk, weights)
    v1_like_table = threshold_table(validation, v1_like_risk, thresholds)

    OUT.mkdir(parents=True, exist_ok=True)
    table.to_csv(OUT / "model_v2_thresholds.csv", index=False)
    baselines.to_csv(OUT / "model_v2_baselines.csv", index=False)
    matched.to_csv(OUT / "model_v2_matched_fpr.csv", index=False)
    scenarios.to_csv(OUT / "model_v2_scenarios.csv")
    segments.to_csv(OUT / "model_v2_segments.csv", index=False)
    v1_like_table.to_csv(OUT / "model_v2_v1_equivalent_thresholds.csv", index=False)

    report = {
        "model_version": metadata["model_version"],
        "status": "development_validation_only",
        "selected_candidate": metadata["selected_candidate"],
        "selected_calibration": metadata["selected_calibration"],
        "feature_contract_sha256": metadata["feature_contract_sha256"],
        "model_sha256": metadata["model_sha256"],
        "training_config_sha256": metadata["training_config_sha256"],
        "features_sha256": hashlib.sha256(DATA.read_bytes()).hexdigest(),
        "validation_rows": int(len(validation)),
        "validation_devices": int(validation.device_id.nunique()),
        "validation_attack_devices": int(
            validation.drop_duplicates("device_id").label.sum()
        ),
        "model_scores": {k: round(v, 6) for k, v in model_metrics.items()},
        "v1_equivalent_scores": {k: round(v, 6) for k, v in v1_like_metrics.items()},
        "calibration_bins": reliability_bins(labels, risk, weights),
        "reporting_threshold": reporting,
        "reporting_threshold_note": (
            "provisional, only to make the per-group tables comparable; the "
            "operating point is chosen in the policy phase"
        ),
        "prevalence_note": (
            "benchmark prevalence is enriched; precision figures are labelled "
            "benchmark_precision and are not production estimates"
        ),
        "evaluated_utc": datetime.now(UTC).isoformat(),
        "policy_selected": False,
        "blind_evaluated": False,
    }
    (OUT / "model_v2_validation_metrics.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, default=str) + "\n"
    )

    print(
        json.dumps(
            {k: v for k, v in report.items() if k != "calibration_bins"},
            indent=2,
            default=str,
        )
    )
    print("\n--- threshold table (validation) ---")
    print(table.round(4).to_string(index=False))
    print("\n--- matched-FPR baseline comparison ---")
    print(matched.to_string(index=False))
    print("\n--- customer-id segments ---")
    print(segments.round(4).to_string(index=False))
