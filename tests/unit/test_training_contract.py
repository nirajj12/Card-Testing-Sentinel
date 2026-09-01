"""Fold integrity, feature-contract enforcement and metric behaviour."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from card_testing_sentinel.features.specification import MODEL_FEATURES
from card_testing_sentinel.ml.folds import assert_fold_integrity, make_device_folds
from card_testing_sentinel.ml.metrics import (
    balanced_training_weights,
    device_weights,
    expected_calibration_error,
    probability_metrics,
)
from card_testing_sentinel.ml.training import (
    NON_FEATURE_COLUMNS,
    assert_feature_contract,
)


def _devices(count: int = 60) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "device_id": [f"dev_{index:04d}" for index in range(count)],
            "scenario": [f"scenario_{index % 5}" for index in range(count)],
        }
    )


def test_folds_are_deterministic_for_a_seed():
    first = make_device_folds(_devices(), 5, seed=7)
    second = make_device_folds(_devices(), 5, seed=7)
    pd.testing.assert_frame_equal(first, second)
    different = make_device_folds(_devices(), 5, seed=8)
    assert not first.equals(different)


def test_every_device_lands_in_exactly_one_fold():
    devices = _devices()
    folds = make_device_folds(devices, 5, seed=7)
    assert set(folds.device_id) == set(devices.device_id)
    assert not folds.device_id.duplicated().any()
    assert set(folds.fold) == set(range(5))


def test_folds_keep_scenarios_balanced():
    folds = make_device_folds(_devices(100), 5, seed=3).merge(
        _devices(100), on="device_id"
    )
    counts = folds.groupby(["fold", "scenario"]).size().unstack(fill_value=0)
    # round-robin within scenario means fold sizes differ by at most one
    assert counts.values.max() - counts.values.min() <= 1


def test_fold_integrity_rejects_held_out_device_leakage():
    devices = _devices()
    folds = make_device_folds(devices, 5, seed=7)
    training = set(devices.device_id)
    with pytest.raises(ValueError, match="held-out devices"):
        assert_fold_integrity(folds, training, {"dev_0001"})


def test_fold_integrity_rejects_an_incomplete_fold_table():
    devices = _devices()
    folds = make_device_folds(devices, 5, seed=7).iloc[:-1]
    with pytest.raises(ValueError, match="exactly the training devices"):
        assert_fold_integrity(folds, set(devices.device_id), set())


def test_a_device_may_not_appear_twice_in_the_fold_input():
    devices = pd.concat([_devices(5), _devices(5)], ignore_index=True)
    with pytest.raises(ValueError, match="exactly once"):
        make_device_folds(devices, 3, seed=1)


def test_feature_contract_assertion_accepts_the_real_order():
    frame = pd.DataFrame(
        {name: [0.0] for name in MODEL_FEATURES} | {"label": [0], "device_id": ["d"]}
    )
    assert_feature_contract(frame)


def test_feature_contract_assertion_rejects_a_reordered_table():
    reordered = list(MODEL_FEATURES)
    reordered[0], reordered[1] = reordered[1], reordered[0]
    frame = pd.DataFrame({name: [0.0] for name in reordered})
    with pytest.raises(ValueError, match="feature order"):
        assert_feature_contract(frame)


def test_grouping_columns_are_never_part_of_the_feature_contract():
    assert not set(NON_FEATURE_COLUMNS) & set(MODEL_FEATURES)


def test_device_weights_give_every_device_equal_mass():
    frame = pd.DataFrame({"device_id": ["a", "a", "a", "b"], "label": [1, 1, 1, 0]})
    weights = device_weights(frame)
    assert weights[:3].sum() == pytest.approx(1.0)
    assert weights[3] == pytest.approx(1.0)


def test_balanced_training_weights_equalise_the_classes():
    frame = pd.DataFrame(
        {"device_id": ["a", "a", "b", "c", "d"], "label": [1, 1, 0, 0, 0]}
    )
    weights = balanced_training_weights(frame)
    attack = weights[frame.label.eq(1).to_numpy()].sum()
    legitimate = weights[frame.label.eq(0).to_numpy()].sum()
    assert attack == pytest.approx(0.5)
    assert legitimate == pytest.approx(0.5)


def test_expected_calibration_error_is_zero_for_a_perfect_calibrator():
    labels = np.array([0, 0, 1, 1])
    scores = np.array([0.0, 0.0, 1.0, 1.0])
    weights = np.ones(4)
    assert expected_calibration_error(labels, scores, weights) == pytest.approx(0.0)


def test_probability_metrics_report_every_required_measure():
    rng = np.random.default_rng(0)
    labels = rng.integers(0, 2, 200)
    scores = rng.random(200)
    metrics = probability_metrics(labels, scores, np.ones(200))
    assert set(metrics) == {
        "pr_auc",
        "roc_auc",
        "brier",
        "log_loss",
        "ece",
        "positive_rate",
    }
    assert all(np.isfinite(value) for value in metrics.values())
