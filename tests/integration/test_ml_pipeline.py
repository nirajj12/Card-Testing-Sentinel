import json
from pathlib import Path

import joblib
import pandas as pd
import yaml

from card_testing_sentinel.ml.eda import training_eda
from card_testing_sentinel.ml.evaluation import (
    evaluate_validation_rows,
    replay_operational_policy,
    summarize_sequential_decisions,
)
from card_testing_sentinel.ml.generation import write_development_bundle
from card_testing_sentinel.ml.training import train_development_model
from card_testing_sentinel.ml.validation import validate_dataset


def test_small_development_pipeline_without_blind_evidence(tmp_path):
    generation = {
        "dataset_name": "test-development-synthetic",
        "seed": 20260825,
        "start_timestamp": "2026-01-01T00:00:00+00:00",
        "currency": "USD",
        "validation_fraction": 0.2,
        "device_counts": {
            "normal_standard": 20,
            "normal_bad_luck": 10,
            "flash_standard": 10,
            "flash_hard_retry": 10,
            "attack_burst": 10,
            "attack_evasive": 10,
            "attack_patient": 10,
        },
    }
    data_dir = tmp_path / "development"
    manifest = write_development_bundle(generation, data_dir)
    assert manifest["blind_test_included"] is False
    validation = validate_dataset(data_dir)
    assert validation["status"] == "passed"
    assert validation["feature_count"] == 44

    features = pd.read_csv(data_dir / "events_with_features.csv")
    raw = pd.read_csv(data_dir / "raw_events.csv")
    training_ids = set(features.loc[features.split.eq("train"), "device_id"])
    eda = training_eda(
        features.loc[features.device_id.isin(training_ids)],
        raw.loc[raw.device_id.isin(training_ids)],
        tmp_path / "eda",
    )
    assert eda["scope"] == "training devices only"

    config = {
        "seed": 20260825,
        "folds": 2,
        "candidate_grids": {
            "logistic_regression": {"C": [1.0], "max_iter": 200},
            "hist_gradient_boosting": [],
        },
        "calibration_methods": ["none", "isotonic"],
    }
    config_path = tmp_path / "training.yaml"
    config_path.write_text(yaml.safe_dump(config))
    training_dir = tmp_path / "training"
    result = train_development_model(
        data_dir / "events_with_features.csv", config_path, training_dir
    )
    assert result["blind_evidence_read"] is False
    model_path = training_dir / "development_model.joblib"
    row_metrics = evaluate_validation_rows(
        model_path, data_dir / "events_with_features.csv"
    )
    assert row_metrics["blind_evidence_read"] is False

    artifact = joblib.load(model_path)
    policy = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "artifacts/policy/operational_policy.json"
        ).read_text()
    )["policy"]
    validation_ids = set(features.loc[features.split.eq("validation"), "device_id"])
    decisions = replay_operational_policy(
        raw.loc[raw.device_id.isin(validation_ids)], artifact, policy
    )
    summary = summarize_sequential_decisions(decisions)
    assert summary["devices"] == len(validation_ids)
