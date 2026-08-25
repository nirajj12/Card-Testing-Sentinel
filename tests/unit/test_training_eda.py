import numpy as np
import pandas as pd
import pytest

from card_testing_sentinel.common.exceptions import ModelTrainingError
from card_testing_sentinel.evaluation.eda import (
    feature_correlations,
    feature_summary,
    run_training_eda,
    scenario_membership,
    univariate_strength,
)
from card_testing_sentinel.features.spec import MODEL_FEATURES
from card_testing_sentinel.modeling.data import ModelingView


def _view() -> ModelingView:
    values = np.tile(np.arange(6, dtype=float)[:, None], (1, len(MODEL_FEATURES)))
    X = pd.DataFrame(values, columns=MODEL_FEATURES)
    metadata = pd.DataFrame(
        {
            "event_id": [f"e{i}" for i in range(6)],
            "event_sequence": range(6),
            "timestamp": pd.date_range("2026-01-01", periods=6, freq="min"),
            "device_id": ["a", "a", "b", "c", "d", "e"],
            "session_id": ["s1", "s1", "s2", "s3", "s4", "s5"],
            "population": ["normal"] * 3 + ["attack"] * 3,
            "attack_subtype": [pd.NA] * 3 + ["burst"] * 3,
            "scenario_tag": ["normal_standard"] * 3 + ["attack_burst"] * 3,
        }
    )
    return ModelingView(X, pd.Series([0, 0, 0, 1, 1, 1], name="label"), metadata)


def test_feature_summary_order_and_correlation_detection():
    view = _view()
    summary = feature_summary(view.X)
    correlations = feature_correlations(view.X)
    assert tuple(summary["feature"]) == MODEL_FEATURES
    assert summary.columns.tolist()[0] == "feature"
    assert correlations[["pearson", "spearman"]].abs().max().max() == 1.0


def test_univariate_strength_checks_both_directions_with_device_weights():
    result = univariate_strength(_view())
    assert set(result["direction"]) <= {"high", "low"}
    assert len(result) == 26


def test_scenario_membership_preserves_returning_device_overlap():
    frame = pd.DataFrame(
        {
            "session_id": ["s1", "s2"],
            "device_id": ["same", "same"],
            "scenario_tag": ["normal_standard", "normal_bad_luck"],
        }
    )
    result = scenario_membership(frame)
    assert sum(item["distinct_devices_ever_tagged"] for item in result) == 2


def test_eda_rejects_held_out_rows_before_writing(tmp_path):
    view = _view()
    metadata = view.metadata.assign(split="validation")
    with pytest.raises(ModelTrainingError, match="non-training"):
        run_training_eda(
            ModelingView(view.X, view.y, metadata),
            checksums={},
            dataset_version="v4",
            metrics_dir=tmp_path / "metrics",
            figure_dir=tmp_path / "figures",
        )
