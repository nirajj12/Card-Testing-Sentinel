"""Gate 6 (corrective pass, continued): behavioral tests for the previously
low-coverage ``v2.evaluation.metrics`` and ``v2.modeling.candidates``
modules. Synthetic fixtures only.
"""

import numpy as np
import pandas as pd
import pytest

from card_testing_sentinel.v2.evaluation.metrics import (
    expected_calibration_error,
    probability_metrics,
    reliability_table,
    wilson_interval,
)
from card_testing_sentinel.v2.modeling.candidates import (
    build_candidate,
    candidate_specs,
    fit_candidate,
)
from card_testing_sentinel.v2.modeling.features import MODEL_FEATURE_COLUMNS


def test_expected_calibration_error_is_zero_for_a_perfectly_calibrated_model():
    labels = np.array([0, 0, 1, 1])
    probabilities = np.array([0.0, 0.0, 1.0, 1.0])
    weights = np.ones(4)
    assert expected_calibration_error(labels, probabilities, weights) == pytest.approx(
        0.0
    )


def test_expected_calibration_error_is_positive_for_a_miscalibrated_model():
    labels = np.array([0, 0, 0, 0])
    probabilities = np.array([0.9, 0.9, 0.9, 0.9])
    weights = np.ones(4)
    ece = expected_calibration_error(labels, probabilities, weights)
    assert ece == pytest.approx(0.9, abs=1e-6)


def test_reliability_table_has_one_row_per_bin_with_correct_bounds():
    rng = np.random.RandomState(0)
    labels = rng.randint(0, 2, size=50)
    probabilities = rng.rand(50)
    weights = np.ones(50)
    table = reliability_table(labels, probabilities, weights, bins=5)
    assert len(table) == 5
    assert list(table["bin"]) == [0, 1, 2, 3, 4]
    np.testing.assert_allclose(table["lower"], [0.0, 0.2, 0.4, 0.6, 0.8])
    np.testing.assert_allclose(table["upper"], [0.2, 0.4, 0.6, 0.8, 1.0])
    assert table["rows"].sum() == 50


def test_reliability_table_empty_bin_reports_nan_not_a_crash():
    labels = np.array([1, 1])
    probabilities = np.array([0.95, 0.99])  # nothing falls in the low bins
    weights = np.ones(2)
    table = reliability_table(labels, probabilities, weights, bins=10)
    assert table.loc[0, "rows"] == 0
    assert np.isnan(table.loc[0, "mean_probability"])
    assert np.isnan(table.loc[0, "observed_rate"])


def test_probability_metrics_without_threshold_omits_precision_recall_f1():
    rng = np.random.RandomState(1)
    labels = rng.randint(0, 2, size=100)
    probabilities = rng.rand(100)
    weights = np.ones(100)
    result = probability_metrics(labels, probabilities, weights)
    assert {"pr_auc", "roc_auc", "brier", "log_loss", "ece_10"} <= set(result)
    assert "precision" not in result


def test_probability_metrics_with_threshold_includes_precision_recall_f1():
    rng = np.random.RandomState(1)
    labels = rng.randint(0, 2, size=100)
    probabilities = rng.rand(100)
    weights = np.ones(100)
    result = probability_metrics(labels, probabilities, weights, threshold=0.5)
    assert result["threshold"] == 0.5
    assert 0.0 <= result["precision"] <= 1.0
    assert 0.0 <= result["recall"] <= 1.0
    assert 0.0 <= result["f1"] <= 1.0


def test_wilson_interval_returns_nan_for_zero_denominator():
    low, high = wilson_interval(0, 0)
    assert np.isnan(low)
    assert np.isnan(high)


def test_wilson_interval_bounds_contain_the_point_estimate():
    low, high = wilson_interval(30, 100)
    assert low < 0.30 < high


# ---------------------------------------------------------------------------
# candidates.py
# ---------------------------------------------------------------------------


CANDIDATE_CONFIG = {
    "candidate_grids": {
        "logistic_regression": {"C": [0.1, 1.0], "max_iter": 200},
        "hist_gradient_boosting": [
            {
                "learning_rate": 0.05,
                "max_leaf_nodes": 15,
                "max_iter": 20,
                "l2_regularization": 1.0,
            }
        ],
    }
}


def test_candidate_specs_yields_one_spec_per_grid_point():
    specs = list(candidate_specs(CANDIDATE_CONFIG))
    assert len(specs) == 3  # 2 logistic + 1 HGB
    families = [spec["family"] for spec in specs]
    assert families.count("logistic_regression") == 2
    assert families.count("hist_gradient_boosting") == 1


def test_build_candidate_rejects_unknown_family():
    with pytest.raises(ValueError, match="unknown candidate family"):
        build_candidate("neural_network", {}, seed=0)


def test_fit_candidate_rejects_wrong_column_order():
    rng = np.random.RandomState(0)
    frame = pd.DataFrame({name: rng.rand(10) for name in MODEL_FEATURE_COLUMNS})
    scrambled = frame[list(reversed(MODEL_FEATURE_COLUMNS))]
    model = build_candidate("logistic_regression", {"C": 1.0, "max_iter": 100}, seed=0)
    labels = (frame[MODEL_FEATURE_COLUMNS[0]] > 0.5).astype(int)
    with pytest.raises(ValueError, match="centralized feature allowlist"):
        fit_candidate(model, "logistic_regression", scrambled, labels, np.ones(10))


def test_fit_candidate_trains_a_real_logistic_regression_pipeline():
    rng = np.random.RandomState(0)
    frame = pd.DataFrame({name: rng.rand(40) for name in MODEL_FEATURE_COLUMNS})
    labels = (frame[MODEL_FEATURE_COLUMNS[0]] > 0.5).astype(int)
    model = build_candidate("logistic_regression", {"C": 1.0, "max_iter": 200}, seed=0)
    fitted = fit_candidate(model, "logistic_regression", frame, labels, np.ones(40))
    predictions = fitted.predict_proba(frame)[:, 1]
    assert predictions.shape == (40,)
    assert np.all((predictions >= 0) & (predictions <= 1))
