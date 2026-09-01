"""Customer-aware grouped cross-validation folds.

v1 grouped by device: a device's attempts are one behavioural sequence, so
splitting its rows would let a model see part of a sequence it is being asked
to score.

v2 needs a wider group. A customer can own several devices, and the customer
features summarise behaviour across all of them -- so two devices of the same
account in different folds would leak that account's own history into the
fold scoring it. The group key is therefore the customer where one exists and
the device otherwise.

Assignment hashes the group key, so it is reproducible from the seed alone
and does not depend on row order.
"""

from __future__ import annotations

import hashlib

import pandas as pd


def group_key(devices: pd.DataFrame) -> pd.Series:
    """Customer identity when present, device identity otherwise."""
    if "customer_id" not in devices.columns:
        return devices.device_id.astype(str)
    return devices.customer_id.where(
        devices.customer_id.notna(), devices.device_id
    ).astype(str)


def make_grouped_folds(devices: pd.DataFrame, n_folds: int, seed: int) -> pd.DataFrame:
    """`devices` needs `device_id`, `scenario` and ideally `customer_id`.

    Scenario-stratified round-robin over groups keeps each fold's family mix
    close to the population's, which matters because the rare attack families
    would otherwise land unevenly.
    """
    required = {"device_id", "scenario"}
    if not required <= set(devices.columns):
        raise ValueError(f"fold input requires {sorted(required)}")
    if devices.device_id.duplicated().any():
        raise ValueError("each device must appear exactly once")
    if n_folds < 2:
        raise ValueError("cross-validation needs at least two folds")

    working = devices.copy()
    working["group_id"] = group_key(working)
    # One fold per GROUP, then broadcast to that group's devices. A group's
    # scenario is taken from its first device: a group spanning two families
    # would otherwise get two different fold assignments.
    groups = (
        working.groupby("group_id").agg(scenario=("scenario", "first")).reset_index()
    )
    rows: list[dict] = []
    for scenario, block in groups.groupby("scenario", sort=True):
        ordered = sorted(
            block.group_id,
            key=lambda value: hashlib.sha256(
                f"{seed}:{scenario}:{value}".encode()
            ).hexdigest(),
        )
        rows.extend(
            {"group_id": group, "fold": index % n_folds}
            for index, group in enumerate(ordered)
        )
    assignment = pd.DataFrame(rows)
    return working[["device_id", "group_id", "scenario"]].merge(
        assignment, on="group_id", how="left", validate="many_to_one"
    )


def assert_fold_integrity(folds: pd.DataFrame, n_folds: int) -> None:
    if folds.fold.isna().any():
        raise RuntimeError("some devices were never assigned a fold")
    if sorted(folds.fold.unique()) != list(range(n_folds)):
        raise RuntimeError("fold labels are not a complete 0..n-1 range")
    straddling = folds.groupby("group_id").fold.nunique()
    if (straddling > 1).any():
        offenders = straddling[straddling > 1].index.tolist()[:3]
        raise RuntimeError(f"groups straddle folds: {offenders}")
