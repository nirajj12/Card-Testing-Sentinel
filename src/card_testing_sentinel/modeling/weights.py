"""Device-equal evaluation and class-balanced training weights."""

import numpy as np
import pandas as pd

from card_testing_sentinel.common.exceptions import ModelTrainingError


def evaluation_weights(device_ids: pd.Series) -> np.ndarray:
    counts = device_ids.value_counts()
    weights = device_ids.map(1.0 / counts).to_numpy(dtype=float)
    if not np.isfinite(weights).all() or (weights <= 0).any():
        raise ModelTrainingError("evaluation weights must be finite and positive")
    return weights


def training_weights(device_ids: pd.Series, labels: pd.Series) -> np.ndarray:
    frame = pd.DataFrame(
        {"device_id": device_ids.to_numpy(), "label": labels.to_numpy()}
    )
    stable = frame.groupby("device_id")["label"].nunique()
    if stable.max() != 1:
        raise ModelTrainingError("training weight labels are not stable by device")
    per_device = evaluation_weights(frame["device_id"])
    device_labels = frame.drop_duplicates("device_id")["label"]
    class_counts = device_labels.value_counts()
    if len(class_counts) != 2:
        raise ModelTrainingError("training partition must contain both classes")
    factors = frame["label"].map(1.0 / class_counts).to_numpy(dtype=float)
    weights = per_device * factors
    weights /= weights.mean()
    if not np.isfinite(weights).all() or (weights <= 0).any():
        raise ModelTrainingError("training weights must be finite and positive")
    return weights
