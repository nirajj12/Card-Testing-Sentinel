"""Deterministic device-grouped cross-validation folds.

A device's attempts are one behavioural sequence, so a device must live
entirely inside one fold: splitting its rows would let the model see part of
a sequence it is being asked to score. Folds are assigned by hashing the
device id, so the assignment is reproducible from the seed alone and does
not depend on row order.

Scenario-stratified round-robin keeps each fold's scenario mix close to the
population's, which matters because the rare attack families would otherwise
land unevenly across five folds.
"""

from __future__ import annotations

import hashlib

import pandas as pd


def make_device_folds(devices: pd.DataFrame, n_folds: int, seed: int) -> pd.DataFrame:
    """`devices` needs `device_id` and `scenario`, one row per device."""
    required = {"device_id", "scenario"}
    if not required <= set(devices.columns):
        raise ValueError(f"fold input requires {sorted(required)}")
    if devices.device_id.duplicated().any():
        raise ValueError("each device must appear exactly once")
    if n_folds < 2:
        raise ValueError("cross-validation needs at least two folds")

    rows: list[dict] = []
    for scenario, group in devices.groupby("scenario", sort=True):
        ordered = sorted(
            group.device_id,
            key=lambda value: hashlib.sha256(
                f"{seed}:{scenario}:{value}".encode()
            ).hexdigest(),
        )
        rows.extend(
            {"device_id": device, "fold": index % n_folds}
            for index, device in enumerate(ordered)
        )
    return pd.DataFrame(rows).sort_values("device_id").reset_index(drop=True)


def assert_fold_integrity(
    folds: pd.DataFrame,
    training_devices: set[str],
    held_out_devices: set[str],
) -> None:
    """Every training device has exactly one fold, and no validation device
    ever entered the fold table."""
    assigned = set(folds.device_id)
    if assigned != training_devices:
        missing = len(training_devices - assigned)
        extra = len(assigned - training_devices)
        raise ValueError(
            f"fold table must cover exactly the training devices "
            f"(missing {missing}, unexpected {extra})"
        )
    if folds.device_id.duplicated().any():
        raise ValueError("a device was assigned to more than one fold")
    leaked = assigned & held_out_devices
    if leaked:
        raise ValueError(f"{len(leaked)} held-out devices entered the folds")
    for fold in sorted(folds.fold.unique()):
        holdout = set(folds.loc[folds.fold.eq(fold), "device_id"])
        if holdout & (training_devices - holdout) != set():
            raise ValueError("fit and holdout devices overlap")
