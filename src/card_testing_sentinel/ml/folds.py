import hashlib

import pandas as pd


def make_device_folds(training_devices: pd.DataFrame, n_folds: int = 5) -> pd.DataFrame:
    """Stratified deterministic round-robin folds at the device boundary."""
    required = {"device_id", "scenario_tag", "split"}
    if not required <= set(training_devices):
        raise ValueError(f"fold input requires {sorted(required)}")
    if set(training_devices.split) != {"train"}:
        raise ValueError("fold assignments may contain training devices only")
    if training_devices.device_id.duplicated().any():
        raise ValueError("each device must appear exactly once")
    rows: list[dict] = []
    for scenario, group in training_devices.groupby("scenario_tag", sort=True):
        ordered = sorted(
            group.device_id,
            key=lambda value: hashlib.sha256(
                f"20260825:{scenario}:{value}".encode()
            ).hexdigest(),
        )
        rows.extend(
            {"device_id": device, "fold": index % n_folds}
            for index, device in enumerate(ordered)
        )
    return pd.DataFrame(rows).sort_values("device_id").reset_index(drop=True)


def assert_fold_integrity(
    folds: pd.DataFrame, training_device_ids: set[str], validation_device_ids: set[str]
) -> None:
    if set(folds.device_id) != training_device_ids:
        raise ValueError("every and only training device must have one fold")
    if folds.device_id.duplicated().any():
        raise ValueError("device has multiple holdout folds")
    if set(folds.device_id) & validation_device_ids:
        raise ValueError("validation device entered training folds")
    for fold in sorted(folds.fold.unique()):
        holdout = set(folds.loc[folds.fold.eq(fold), "device_id"])
        fit = training_device_ids - holdout
        if fit & holdout:
            raise ValueError("fit and holdout devices overlap")
