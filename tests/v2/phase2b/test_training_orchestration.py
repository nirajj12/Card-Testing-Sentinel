"""Focused coverage for deterministic Phase 2B training helpers."""

import json

import joblib
import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LogisticRegression

from card_testing_sentinel.v2.phase2b.features import MODEL_FEATURE_COLUMNS
from card_testing_sentinel.v2.phase2b.training import (
    _atomic_joblib_dump,
    _candidate_key,
    build_candidate,
    compare_reproduction,
    device_diagnostics,
    diagnostic_device_threshold,
    fit_candidate,
    fit_deployable,
    grouped_oof,
    make_candidate_specs,
    nested_calibrated_oof,
    scenario_shortcut_check,
    sha256_file,
    strongest_single_feature,
    training_eda,
    verify_serialization,
)


def _frame() -> pd.DataFrame:
    rows = []
    scenarios = (
        "normal_standard",
        "normal_bad_luck",
        "flash_standard",
        "flash_hard_retry",
        "attack_burst",
        "attack_evasive",
        "attack_patient",
    )
    subtypes = ("burst", "evasive", "patient")
    for device_number in range(42):
        label = device_number % 2
        for event_number in range(2):
            row = {
                "event_id": f"e-{device_number}-{event_number}",
                "request_id": f"r-{device_number}-{event_number}",
                "device_id": f"d-{device_number}",
                "timestamp": f"2026-01-01T00:{device_number:02d}:{event_number:02d}Z",
                "label": label,
                "attack_subtype": subtypes[device_number % 3] if label else "none",
                "scenario_tag": scenarios[device_number % len(scenarios)],
                "fold": device_number % 3,
            }
            for feature_number, feature in enumerate(MODEL_FEATURE_COLUMNS):
                row[feature] = float(
                    ((device_number + 1) * (feature_number + 3) + event_number) % 17
                )
            rows.append(row)
    return pd.DataFrame(rows)


def _logistic_spec() -> dict:
    return {
        "family": "logistic_regression",
        "parameters": {"C": 1.0, "max_iter": 100},
    }


def test_candidate_helpers_and_grouped_training_paths():
    frame = _frame()
    config = {
        "candidate_grids": {
            "logistic_regression": {"C": [0.1, 1], "max_iter": 100},
            "hist_gradient_boosting": [{"max_iter": 5, "max_leaf_nodes": 7}],
        }
    }
    specs = make_candidate_specs(config)
    assert [item["family"] for item in specs] == [
        "logistic_regression",
        "logistic_regression",
        "hist_gradient_boosting",
    ]

    weights = np.ones(len(frame))
    logistic = fit_candidate(build_candidate(specs[0], 7), specs[0], frame, weights)
    tree = fit_candidate(build_candidate(specs[2], 7), specs[2], frame, weights)
    assert logistic.predict_proba(frame)[:, 1].shape == (len(frame),)
    assert tree.predict_proba(frame.loc[:, MODEL_FEATURE_COLUMNS])[:, 1].shape == (
        len(frame),
    )

    probability, folds, elapsed = grouped_oof(frame, _logistic_spec(), 7)
    assert np.isfinite(probability).all()
    assert len(folds) == 3
    assert elapsed >= 0

    raw, calibrated, isolation = nested_calibrated_oof(
        frame, _logistic_spec(), "sigmoid", 7
    )
    assert np.isfinite(raw).all() and np.isfinite(calibrated).all()
    assert all(row["all_pairwise_device_overlaps"] == 0 for row in isolation)
    artifact = fit_deployable(frame, _logistic_spec(), "none", 7)
    assert artifact.predict_proba(frame).shape == (len(frame),)


def test_diagnostics_shortcuts_and_eda(tmp_path):
    frame = _frame()
    probability = np.linspace(0.01, 0.99, len(frame))
    threshold, devices = diagnostic_device_threshold(frame, probability, 0.1)
    diagnostics = device_diagnostics(devices)
    assert 0 <= threshold <= 1
    assert diagnostics["subtype"]
    assert diagnostics["scenario"]
    assert strongest_single_feature(frame)["feature"] in MODEL_FEATURE_COLUMNS
    assert scenario_shortcut_check(frame)["scenario"]

    raw = frame.loc[:, ["device_id"]].copy()
    raw["session_id"] = [f"s-{index // 2}" for index in range(len(raw))]
    summary = training_eda(frame, raw, tmp_path / "eda")
    assert summary["devices"] == 42
    assert summary["missing_model_values"] == 0
    assert (tmp_path / "eda/feature_summary.csv").is_file()


def test_artifact_io_serialization_and_reproduction(tmp_path, monkeypatch):
    value_path = tmp_path / "value.joblib"
    _atomic_joblib_dump({"answer": 42}, value_path)
    assert joblib.load(value_path) == {"answer": 42}
    assert len(sha256_file(value_path)) == 64

    failed_path = tmp_path / "failed.joblib"
    real_dump = joblib.dump
    monkeypatch.setattr(
        joblib, "dump", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("boom"))
    )
    with pytest.raises(OSError, match="boom"):
        _atomic_joblib_dump({}, failed_path)
    assert not failed_path.exists()
    assert not list(tmp_path.glob(".failed.joblib.*"))
    monkeypatch.setattr(joblib, "dump", real_dump)

    fixture = pd.DataFrame({"a": [0.0, 1.0, 2.0, 3.0], "b": [1.0, 0.0, 1.0, 0.0]})
    model = LogisticRegression(random_state=1).fit(fixture, [0, 0, 1, 1])
    model_path = tmp_path / "model.joblib"
    fixture_path = tmp_path / "fixture.csv"
    expected_path = tmp_path / "separate.json"
    joblib.dump(model, model_path)
    fixture.to_csv(fixture_path, index=False)
    parity = verify_serialization(model_path, fixture_path, expected_path, 1e-12)
    assert parity["maximum_absolute_difference"] == 0

    first, second = tmp_path / "first", tmp_path / "second"
    deterministic = (
        "training/device_folds.csv",
        "metrics/candidate_oof_metrics.csv",
        "metrics/calibration_comparison.csv",
        "metrics/training_selection.json",
        "models/model_feature_contract.json",
        "policy/policy_search_space.json",
        "eda/eda_summary.json",
    )
    for root in (first, second):
        predictions = root / "predictions/training_oof_predictions.csv"
        predictions.parent.mkdir(parents=True)
        pd.DataFrame(
            {"raw_probability": [0.2, 0.8], "calibrated_probability": [0.1, 0.9]}
        ).to_csv(predictions, index=False)
        for relative in deterministic:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"stable": True}) + "\n")
    reproduction = compare_reproduction(first, second, 1e-12)
    assert reproduction["selection_identical"]


def test_candidate_ranking_key_prefers_integrity_metrics():
    row = {
        "worst_subtype_coverage": 0.7,
        "macro_subtype_coverage": 0.8,
        "pr_auc": 0.9,
        "brier": 0.1,
        "cost_rank": 0,
        "family": "logistic_regression",
        "candidate": "lr",
    }
    assert _candidate_key(row)[0:3] == (0.7, 0.8, 0.9)
