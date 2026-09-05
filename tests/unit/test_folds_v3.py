from __future__ import annotations

import pandas as pd

from card_testing_sentinel.ml.folds_v3 import make_leakage_group_folds


def test_multi_device_leakage_groups_never_straddle_folds() -> None:
    devices = pd.DataFrame(
        {
            "device_id": ["d1", "d2", "d3", "d4", "d5", "d6"],
            "scenario": ["a", "a", "a", "b", "b", "b"],
            "leakage_group_id": [
                "actor-1",
                "actor-1",
                "actor-2",
                "actor-3",
                "actor-3",
                "actor-4",
            ],
        }
    )
    folds = make_leakage_group_folds(devices, 2, 42)
    assert (folds.groupby("leakage_group_id").fold.nunique() == 1).all()


def test_fold_assignment_is_row_order_independent() -> None:
    devices = pd.DataFrame(
        {
            "device_id": [f"d{i}" for i in range(10)],
            "scenario": ["a"] * 5 + ["b"] * 5,
            "leakage_group_id": [f"g{i}" for i in range(10)],
        }
    )
    first = make_leakage_group_folds(devices, 2, 99).set_index("device_id").fold
    second = (
        make_leakage_group_folds(devices.sample(frac=1.0, random_state=7), 2, 99)
        .set_index("device_id")
        .fold
    )
    assert first.sort_index().equals(second.sort_index())
