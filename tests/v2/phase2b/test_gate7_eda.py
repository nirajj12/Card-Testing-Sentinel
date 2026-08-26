"""Gate 7 (corrective pass, coverage raise): behavioral tests for
src/card_testing_sentinel/v2/evaluation/eda.py.

training_eda() hard-codes an exact structural boundary (21,338 training rows
across exactly 8,000 devices) as a guard against accidentally running EDA on
validation/blind data or a malformed frame. The cheap, high-value test is the
rejection branch; this file also builds a full synthetic frame that
satisfies the exact boundary so the entire computation body (feature
summaries, correlations, univariate strength, fold stability, and the
written output files) is exercised too -- with device_evaluation_weights and
MODEL_FEATURE_COLUMNS still the real, unmodified production values, never
substituted, so no decision logic under test is bypassed.
"""

import json

import numpy as np
import pandas as pd
import pytest

from card_testing_sentinel.v2.evaluation.eda import training_eda
from card_testing_sentinel.v2.modeling.features import MODEL_FEATURE_COLUMNS

TRAINING_ROWS = 21_338
TRAINING_DEVICES = 8_000


def _tiny_wrong_size_frame(rows=40, devices=10) -> pd.DataFrame:
    rng = np.random.RandomState(0)
    device_ids = [f"device-{i % devices}" for i in range(rows)]
    data = {name: rng.rand(rows) for name in MODEL_FEATURE_COLUMNS}
    data["device_id"] = device_ids
    data["label"] = [i % 2 for i in range(rows)]
    data["scenario_tag"] = [
        "normal_standard" if i % 2 else "attack_burst" for i in range(rows)
    ]
    data["attack_subtype"] = [np.nan if i % 2 else "burst" for i in range(rows)]
    data["fold"] = [i % 5 for i in range(rows)]
    return pd.DataFrame(data)


def _tiny_raw(device_ids) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "device_id": device_ids,
            "session_id": [f"session-{d}" for d in device_ids],
            "event_type": ["authorization_request"] * len(device_ids),
        }
    )


# ---------------------------------------------------------------------------
# Cheap rejection-branch tests: training_eda only ever accepts the frozen
# training partition, never validation/blind-shaped data.
# ---------------------------------------------------------------------------


def test_training_eda_rejects_wrong_row_count(tmp_path):
    frame = _tiny_wrong_size_frame(rows=40, devices=10)
    with pytest.raises(ValueError, match="frozen training partition only"):
        training_eda(frame, _tiny_raw(frame.device_id), tmp_path / "eda")


def test_training_eda_rejects_wrong_device_count_even_with_right_row_count(tmp_path):
    # Right row count, wrong device count (simulates a validation/blind-like
    # population shape rather than the frozen training partition).
    rng = np.random.RandomState(0)
    data = {name: rng.rand(TRAINING_ROWS) for name in MODEL_FEATURE_COLUMNS}
    data["device_id"] = [f"device-{i % 50}" for i in range(TRAINING_ROWS)]
    data["label"] = [i % 2 for i in range(TRAINING_ROWS)]
    data["scenario_tag"] = ["normal_standard"] * TRAINING_ROWS
    data["attack_subtype"] = [np.nan] * TRAINING_ROWS
    data["fold"] = [i % 5 for i in range(TRAINING_ROWS)]
    frame = pd.DataFrame(data)
    with pytest.raises(ValueError, match="frozen training partition only"):
        training_eda(frame, _tiny_raw(frame.device_id), tmp_path / "eda")


def test_training_eda_never_writes_output_when_the_guard_rejects(tmp_path):
    frame = _tiny_wrong_size_frame()
    output = tmp_path / "eda"
    with pytest.raises(ValueError):
        training_eda(frame, _tiny_raw(frame.device_id), output)
    assert not output.exists()


# ---------------------------------------------------------------------------
# Full happy path against a synthetic frame satisfying the exact frozen
# boundary (21,338 rows / 8,000 devices) -- expensive to construct but cheap
# to execute (pure vectorized pandas/sklearn calls over ~21k rows).
# ---------------------------------------------------------------------------


def _full_boundary_frame(seed=0):
    rng = np.random.RandomState(seed)
    # 8,000 devices; distribute 21,338 rows across them (some devices get 2
    # rows, some 3, so the total is exactly 21,338).
    extra = TRAINING_ROWS - TRAINING_DEVICES * 2  # devices needing a 3rd row
    device_row_counts = [3] * extra + [2] * (TRAINING_DEVICES - extra)
    rng.shuffle(device_row_counts)
    device_ids = []
    fold_by_device = {}
    label_by_device = {}
    scenario_by_device = {}
    subtype_by_device = {}
    for index, count in enumerate(device_row_counts):
        device = f"device-{index:05d}"
        device_ids.extend([device] * count)
        fold_by_device[device] = index % 5
        is_attack = index % 4 == 0
        label_by_device[device] = int(is_attack)
        scenario_by_device[device] = "attack_burst" if is_attack else "normal_standard"
        subtype_by_device[device] = "burst" if is_attack else np.nan
    assert len(device_ids) == TRAINING_ROWS

    data = {name: rng.rand(TRAINING_ROWS) for name in MODEL_FEATURE_COLUMNS}
    data["device_id"] = device_ids
    data["label"] = [label_by_device[d] for d in device_ids]
    data["scenario_tag"] = [scenario_by_device[d] for d in device_ids]
    data["attack_subtype"] = [subtype_by_device[d] for d in device_ids]
    data["fold"] = [fold_by_device[d] for d in device_ids]
    frame = pd.DataFrame(data)
    raw = pd.DataFrame(
        {
            "device_id": device_ids,
            "session_id": [f"session-{d}" for d in device_ids],
            "event_type": ["authorization_request"] * len(device_ids),
        }
    )
    return frame, raw


def test_training_eda_full_happy_path_summary_and_outputs(tmp_path):
    frame, raw = _full_boundary_frame()
    output = tmp_path / "eda"
    summary = training_eda(frame, raw, output)

    assert summary["devices"] == TRAINING_DEVICES
    assert summary["precheck_rows"] == TRAINING_ROWS
    assert summary["lifecycle_events"] == len(raw)
    # Device count and row count must remain visibly distinct denominators.
    assert summary["devices"] != summary["precheck_rows"]
    assert sum(summary["label_devices"].values()) == TRAINING_DEVICES
    assert sum(summary["label_rows"].values()) == TRAINING_ROWS
    assert 0.0 <= summary["device_weighted_positive_rate"] <= 1.0
    assert 0.0 <= summary["row_weighted_positive_rate"] <= 1.0

    expected_files = [
        "training_feature_summary.csv",
        "training_scenario_feature_distributions.csv",
        "training_feature_correlations.csv",
        "training_high_correlation_pairs.csv",
        "training_univariate_strength.csv",
        "training_fold_feature_stability.csv",
    ]
    for name in expected_files:
        assert (output / name).exists(), name

    feature_summary = pd.read_csv(output / "training_feature_summary.csv")
    assert set(feature_summary.feature) == set(MODEL_FEATURE_COLUMNS)

    strength = pd.read_csv(output / "training_univariate_strength.csv")
    # Sorted descending by device-weighted F1: the first row's F1 must be the
    # maximum across all features.
    assert strength.iloc[0].device_weighted_f1 == pytest.approx(
        strength.device_weighted_f1.max()
    )


def test_training_eda_is_deterministic_across_repeated_runs(tmp_path):
    frame, raw = _full_boundary_frame()
    first_dir = tmp_path / "eda_first"
    second_dir = tmp_path / "eda_second"
    first_summary = training_eda(frame.copy(), raw.copy(), first_dir)
    second_summary = training_eda(frame.copy(), raw.copy(), second_dir)
    assert json.dumps(first_summary, sort_keys=True) == json.dumps(
        second_summary, sort_keys=True
    )
    for name in ["training_feature_summary.csv", "training_feature_correlations.csv"]:
        assert (first_dir / name).read_text() == (second_dir / name).read_text()


def test_training_eda_scenario_denominators_use_correct_grouping(tmp_path):
    frame, raw = _full_boundary_frame()
    output = tmp_path / "eda"
    summary = training_eda(frame, raw, output)
    # scenario_devices is a per-device (not per-row) denominator: it must sum
    # to the device count, not the row count.
    assert sum(summary["scenario_devices"].values()) == TRAINING_DEVICES
    # subtype_devices only counts attack devices (attack_subtype not NaN).
    assert sum(summary["subtype_devices"].values()) == summary["label_devices"]["1"]
