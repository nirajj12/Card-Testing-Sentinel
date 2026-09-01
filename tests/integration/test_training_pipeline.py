"""End-to-end training and evaluation on a small deterministic dataset.

Uses a reduced config so it stays fast; the shape of every check is
independent of the row count. No blind data exists or is read.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest
import yaml

from card_testing_sentinel.features.batch import build_feature_table
from card_testing_sentinel.features.specification import (
    MODEL_FEATURES,
    MODEL_FEATURES_SHA256,
)
from card_testing_sentinel.ml.candidates import Candidate, candidate_grid
from card_testing_sentinel.ml.evaluation import (
    CARD_HISTORY_FEATURES,
    baseline_comparison,
    device_outcomes,
    device_summary,
    merchant_metrics,
    rule_scores,
    run_ablation,
    scenario_metrics,
    threshold_sweep,
)
from card_testing_sentinel.ml.generator import (
    generate_development_dataset,
    load_config,
    write_dataset,
)
from card_testing_sentinel.ml.training import train_development_model

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def small_config() -> dict:
    config = copy.deepcopy(load_config(ROOT / "configs/training.yaml"))
    config["splits"]["train"]["devices"] = 420
    config["splits"]["validation"]["devices"] = 200
    config["training"]["folds"] = 3
    config["training"]["candidate_grids"]["logistic_regression"]["C"] = [1.0, 10.0]
    config["training"]["candidate_grids"]["hist_gradient_boosting"] = [
        {
            "learning_rate": 0.1,
            "max_leaf_nodes": 15,
            "max_iter": 60,
            "l2_regularization": 1.0,
        }
    ]
    return config


@pytest.fixture(scope="module")
def trained(tmp_path_factory, small_config) -> dict:
    workspace = tmp_path_factory.mktemp("training")
    data_dir = workspace / "data"
    bundle = generate_development_dataset(small_config)
    write_dataset(bundle, data_dir)
    features = build_feature_table(bundle["raw_events"], bundle["labels"])
    features.to_csv(data_dir / "features.csv", index=False, lineterminator="\n")

    config_path = workspace / "training.yaml"
    config_path.write_text(yaml.safe_dump(small_config, sort_keys=True))
    model_dir = workspace / "model"
    metadata = train_development_model(
        data_dir / "features.csv", config_path, model_dir
    )
    return {
        "workspace": workspace,
        "model_dir": model_dir,
        "config_path": config_path,
        "data_dir": data_dir,
        "metadata": metadata,
        "features": features,
        "config": small_config,
    }


def test_training_produces_a_labelled_development_candidate(trained):
    metadata = trained["metadata"]
    assert metadata["status"] == "development_frozen_candidate"
    assert metadata["final"] is False
    assert metadata["blind_evaluated"] is False
    assert metadata["family"] in {"logistic_regression", "hist_gradient_boosting"}
    assert metadata["selected_calibration"] in {"none", "sigmoid", "isotonic"}


def test_metadata_hashes_bind_the_dataset_config_and_feature_contract(trained):
    metadata = trained["metadata"]
    manifest = json.loads((trained["data_dir"] / "manifest.json").read_text())
    assert metadata["feature_contract_sha256"] == MODEL_FEATURES_SHA256
    assert metadata["dataset_config_sha256"] == manifest["config_sha256"]
    assert metadata["feature_count"] == len(MODEL_FEATURES)
    assert metadata["training_config_sha256"]


def test_every_candidate_is_scored_and_selection_uses_pr_auc(trained):
    comparison = pd.DataFrame(trained["metadata"]["cross_validation"])
    expected = {c.identifier for c in candidate_grid(trained["config"]["training"])}
    assert set(comparison.candidate) == expected
    assert trained["metadata"]["selection_metric"].startswith("device-weighted PR-AUC")
    best = comparison.sort_values("pr_auc", ascending=False).iloc[0].candidate
    assert trained["metadata"]["selected_candidate"] == best


def test_the_artifact_scores_finite_values_in_contract_order(trained):
    artifact = joblib.load(trained["model_dir"] / "risk_model.joblib")
    assert artifact.feature_names == MODEL_FEATURES
    assert artifact.feature_contract_sha256 == MODEL_FEATURES_SHA256
    scores = artifact.score_frame(
        trained["features"].loc[:, list(MODEL_FEATURES)].head(50)
    )
    assert np.isfinite(scores).all()
    assert ((scores >= 0) & (scores <= 1)).all()


def test_training_is_reproducible(trained, small_config, tmp_path):
    """Same dataset, config and seed -> the same selection and the same
    cross-validation numbers."""
    config_path = tmp_path / "training.yaml"
    config_path.write_text(yaml.safe_dump(small_config, sort_keys=True))
    repeat = train_development_model(
        trained["data_dir"] / "features.csv", config_path, tmp_path / "model"
    )
    assert repeat["selected_candidate"] == trained["metadata"]["selected_candidate"]
    assert repeat["selected_calibration"] == trained["metadata"]["selected_calibration"]
    for left, right in zip(
        repeat["cross_validation"], trained["metadata"]["cross_validation"], strict=True
    ):
        assert left["candidate"] == right["candidate"]
        assert left["pr_auc"] == pytest.approx(right["pr_auc"], abs=1e-12)


def test_folds_never_touch_the_validation_split(trained):
    folds = pd.read_csv(trained["model_dir"] / "device_folds.csv")
    features = trained["features"]
    training_devices = set(features.loc[features.split.eq("train"), "device_id"])
    validation_devices = set(features.loc[features.split.eq("validation"), "device_id"])
    assert set(folds.device_id) == training_devices
    assert not set(folds.device_id) & validation_devices


def test_calibration_alternatives_are_all_compared(trained):
    methods = {row["method"] for row in trained["metadata"]["calibration_comparison"]}
    assert methods == {"none", "sigmoid", "isotonic"}


def test_calibration_is_only_adopted_when_it_earns_its_place(trained):
    """A calibrator must improve Brier without materially costing PR-AUC --
    otherwise raw scores are kept."""
    rows = {r["method"]: r for r in trained["metadata"]["calibration_comparison"]}
    chosen = trained["metadata"]["selected_calibration"]
    raw = rows["none"]
    tolerance = trained["config"]["training"]["pr_auc_tolerance"]
    if chosen != "none":
        assert rows[chosen]["brier"] <= raw["brier"]
        assert rows[chosen]["pr_auc"] >= raw["pr_auc"] - tolerance


# --- baselines are measured on one shared population ------------------------


@pytest.fixture(scope="module")
def evaluated(trained) -> dict:
    artifact = joblib.load(trained["model_dir"] / "risk_model.joblib")
    features = trained["features"]
    validation = features.loc[features.split.eq("validation")].reset_index(drop=True)
    risk = artifact.score_frame(validation.loc[:, list(MODEL_FEATURES)])
    return {
        "validation": validation,
        "risk": risk,
        "rules": rule_scores(validation),
        "artifact": artifact,
        "training": features.loc[features.split.eq("train")].reset_index(drop=True),
    }


def test_all_baselines_are_scored_on_the_identical_population(evaluated, trained):
    comparison = baseline_comparison(
        evaluated["validation"],
        evaluated["risk"],
        evaluated["rules"],
        trained["config"]["evaluation"],
    )
    families = set(comparison.family)
    assert {
        "baseline",
        "request_count",
        "rules_only",
        "model_only",
        "model_and_rules",
    } <= families
    # identical denominators everywhere -- otherwise the comparison is a lie
    assert comparison.attack_devices.nunique() == 1
    assert comparison.legitimate_devices.nunique() == 1


def test_no_sentinel_baseline_has_no_friction_and_no_detection(evaluated, trained):
    comparison = baseline_comparison(
        evaluated["validation"],
        evaluated["risk"],
        evaluated["rules"],
        trained["config"]["evaluation"],
    )
    row = comparison.loc[comparison.approach.eq("no_sentinel")].iloc[0]
    assert row.attack_device_recall == 0.0
    assert row.legitimate_device_fpr == 0.0
    assert row.attack_never_detected == row.attack_devices


def test_rules_only_baseline_uses_the_real_runtime_rules(evaluated):
    """The rules baseline must be the deployed rule layer, not a copy."""
    from card_testing_sentinel.policy.rules import evaluate_rules

    row = evaluated["validation"].loc[:, list(MODEL_FEATURES)].iloc[0].to_dict()
    assert evaluated["rules"][0] == evaluate_rules(row)[0]


def test_threshold_sweep_is_monotone_in_the_right_direction(evaluated):
    sweep = threshold_sweep(evaluated["validation"], evaluated["risk"])
    assert sweep.attempt_recall.is_monotonic_decreasing
    assert sweep.attempt_fpr.is_monotonic_decreasing


def test_device_level_evaluation_reports_detection_delay(evaluated):
    devices = device_outcomes(evaluated["validation"], evaluated["risk"] >= 0.6)
    summary = device_summary(devices)
    assert summary["attack_devices"] + summary["legitimate_devices"] == len(devices)
    assert (
        summary["attack_detected"] + summary["attack_never_detected"]
        == summary["attack_devices"]
    )
    if summary["attack_detected"]:
        assert summary["median_first_detection_attempt"] >= 1


def test_per_scenario_and_per_merchant_breakdowns_cover_every_group(evaluated):
    flagged = evaluated["risk"] >= 0.6
    scenarios = scenario_metrics(evaluated["validation"], flagged)
    assert set(scenarios.index) == set(evaluated["validation"].scenario.unique())
    assert set(scenarios.population) == {"legitimate", "attack"}

    merchants = merchant_metrics(evaluated["validation"], flagged)
    assert set(merchants.merchant_kind) == set(
        evaluated["validation"].merchant_kind.unique()
    )


def test_card_history_ablation_runs_and_is_flag_rate_matched(evaluated, trained):
    metadata = trained["metadata"]
    candidate = Candidate(
        metadata["selected_candidate"], metadata["family"], metadata["parameters"]
    )
    flag_rate = float((evaluated["risk"] >= 0.6).mean())
    result = run_ablation(
        evaluated["training"],
        evaluated["validation"],
        candidate,
        int(trained["config"]["training"]["seed"]),
        {
            "all_features": MODEL_FEATURES,
            "minus_card_history": tuple(
                n for n in MODEL_FEATURES if n not in CARD_HISTORY_FEATURES
            ),
        },
        flag_rate,
    )
    assert set(result.feature_set) == {"all_features", "minus_card_history"}
    assert (
        result.loc[result.feature_set.eq("minus_card_history"), "features"].iloc[0]
        == len(MODEL_FEATURES) - 3
    )
    # matched flag rate is what makes the two rows comparable at all
    assert result.matched_flag_rate.nunique() == 1
