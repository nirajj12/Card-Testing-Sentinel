import numpy as np
import pandas as pd


def device_evaluation_weights(frame: pd.DataFrame) -> np.ndarray:
    """Give every device total mass one, regardless of its request count."""
    counts = frame.groupby("device_id").device_id.transform("size")
    if (counts <= 0).any():
        raise ValueError("every evaluation row must belong to a device")
    return (1.0 / counts.to_numpy(dtype=float)).astype(float)


def balanced_device_training_weights(frame: pd.DataFrame) -> np.ndarray:
    """Balance class device mass, then divide each device across its rows."""
    required = {"device_id", "label"}
    if not required <= set(frame):
        raise ValueError(f"training rows require {sorted(required)}")
    per_device = frame[["device_id", "label"]].drop_duplicates()
    if per_device.device_id.duplicated().any():
        raise ValueError("a device cannot have multiple labels")
    class_devices = per_device.groupby("label").size()
    if set(class_devices.index) != {0, 1}:
        raise ValueError("training requires both binary classes")
    class_mass = {label: 0.5 / count for label, count in class_devices.items()}
    request_counts = frame.groupby("device_id").size()
    return np.array(
        [
            class_mass[int(label)] / request_counts[device]
            for device, label in zip(frame.device_id, frame.label, strict=True)
        ],
        dtype=float,
    )


def weight_audit(frame: pd.DataFrame, weights: np.ndarray) -> dict:
    audit = frame[["device_id", "label", "scenario_tag"]].copy()
    audit["weight"] = weights
    return {
        "total": float(audit.weight.sum()),
        "by_class": {
            str(key): float(value)
            for key, value in audit.groupby("label").weight.sum().items()
        },
        "by_scenario": {
            str(key): float(value)
            for key, value in audit.groupby("scenario_tag").weight.sum().items()
        },
    }
