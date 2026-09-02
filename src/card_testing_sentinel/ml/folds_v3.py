"""Actor/campaign-safe deterministic folds for Dataset v4.1."""

from __future__ import annotations

import hashlib

import pandas as pd


def make_leakage_group_folds(
    devices: pd.DataFrame, n_folds: int, seed: int
) -> pd.DataFrame:
    required = {"device_id", "scenario", "leakage_group_id"}
    if not required <= set(devices.columns):
        raise ValueError(f"fold input requires {sorted(required)}")
    if devices.device_id.duplicated().any():
        raise ValueError("each device must appear exactly once")
    if devices.leakage_group_id.isna().any():
        raise ValueError("leakage_group_id may not be missing")
    if n_folds < 2:
        raise ValueError("cross-validation needs at least two folds")

    groups = (
        devices.groupby("leakage_group_id", sort=True)
        .agg(scenario=("scenario", "first"), devices=("device_id", "nunique"))
        .reset_index()
    )
    rows: list[dict] = []
    for scenario, block in groups.groupby("scenario", sort=True):
        ordered = sorted(
            block.leakage_group_id.astype(str),
            key=lambda value: hashlib.sha256(
                f"{seed}:{scenario}:{value}".encode()
            ).hexdigest(),
        )
        rows.extend(
            {"leakage_group_id": group, "fold": index % n_folds}
            for index, group in enumerate(ordered)
        )
    assignment = pd.DataFrame(rows)
    result = devices[["device_id", "leakage_group_id", "scenario"]].merge(
        assignment, on="leakage_group_id", how="left", validate="many_to_one"
    )
    assert_leakage_group_fold_integrity(result, n_folds)
    return result


def assert_leakage_group_fold_integrity(folds: pd.DataFrame, n_folds: int) -> None:
    if folds.fold.isna().any():
        raise RuntimeError("some devices were never assigned a fold")
    if sorted(folds.fold.unique()) != list(range(n_folds)):
        raise RuntimeError("fold labels are not a complete 0..n-1 range")
    straddling = folds.groupby("leakage_group_id").fold.nunique()
    if (straddling > 1).any():
        raise RuntimeError("leakage groups straddle CV folds")


def group_audit(labels: pd.DataFrame, folds: pd.DataFrame | None = None) -> dict:
    groups = labels.groupby("leakage_group_id").agg(
        devices=("device_id", "nunique"), scenario=("scenario", "first")
    )
    result = {
        "unique_groups": int(len(groups)),
        "multi_device_groups": int((groups.devices > 1).sum()),
        "largest_group_devices": int(groups.devices.max()),
        "group_size_distribution": {
            str(int(size)): int(count)
            for size, count in groups.devices.value_counts().sort_index().items()
        },
        "groups_by_scenario": {
            str(name): int(count)
            for name, count in groups.groupby("scenario").size().sort_index().items()
        },
    }
    if folds is not None:
        straddling = folds.groupby("leakage_group_id").fold.nunique()
        result["fold_straddling_groups"] = int((straddling > 1).sum())
    return result
