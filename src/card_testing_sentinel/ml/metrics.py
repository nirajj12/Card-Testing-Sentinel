"""Scoring metrics and sample weights.

Every metric here is *device-weighted* by default: each device carries total
weight one, split across its attempts. Without that, a burst attacker with 14
attempts would count fourteen times as much as a one-attempt shopper, and the
headline numbers would silently be "how well do we score chatty devices".
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    log_loss,
    roc_auc_score,
)


def device_weights(frame: pd.DataFrame) -> np.ndarray:
    """Total weight one per device, divided across that device's rows."""
    counts = frame.groupby("device_id").device_id.transform("size")
    if (counts <= 0).any():
        raise ValueError("every row must belong to a device")
    return (1.0 / counts.to_numpy(dtype=float)).astype(float)


def balanced_training_weights(frame: pd.DataFrame) -> np.ndarray:
    """Device weights, additionally balanced so each class carries half the
    total mass. Attack devices are enriched in this benchmark but that is a
    sampling choice, not a prior we want the fit to inherit."""
    per_device = frame[["device_id", "label"]].drop_duplicates("device_id")
    if per_device.device_id.duplicated().any():
        raise ValueError("a device cannot carry two labels")
    class_devices = per_device.groupby("label").size()
    if set(class_devices.index) != {0, 1}:
        raise ValueError("training needs both classes present")
    class_mass = {label: 0.5 / count for label, count in class_devices.items()}
    request_counts = frame.groupby("device_id").size()
    return np.array(
        [
            class_mass[int(label)] / request_counts[device]
            for device, label in zip(frame.device_id, frame.label, strict=True)
        ],
        dtype=float,
    )


def expected_calibration_error(
    labels: np.ndarray, scores: np.ndarray, weights: np.ndarray, bins: int = 10
) -> float:
    """Weighted ECE over equal-width score bins."""
    edges = np.linspace(0.0, 1.0, bins + 1)
    index = np.clip(np.digitize(scores, edges[1:-1], right=False), 0, bins - 1)
    total = weights.sum()
    error = 0.0
    for bucket in range(bins):
        mask = index == bucket
        mass = weights[mask].sum()
        if mass <= 0:
            continue
        observed = np.average(labels[mask], weights=weights[mask])
        predicted = np.average(scores[mask], weights=weights[mask])
        error += (mass / total) * abs(observed - predicted)
    return float(error)


def probability_metrics(
    labels, scores, weights=None, *, ece_bins: int = 10
) -> dict[str, float]:
    labels = np.asarray(labels, dtype=int)
    scores = np.clip(np.asarray(scores, dtype=float), 1e-9, 1 - 1e-9)
    weights = (
        np.ones_like(scores) if weights is None else np.asarray(weights, dtype=float)
    )
    return {
        "pr_auc": float(average_precision_score(labels, scores, sample_weight=weights)),
        "roc_auc": float(roc_auc_score(labels, scores, sample_weight=weights)),
        "brier": float(brier_score_loss(labels, scores, sample_weight=weights)),
        "log_loss": float(
            log_loss(labels, scores, sample_weight=weights, labels=[0, 1])
        ),
        "ece": expected_calibration_error(labels, scores, weights, bins=ece_bins),
        "positive_rate": float(np.average(labels, weights=weights)),
    }


def reliability_bins(
    labels, scores, weights=None, bins: int = 10
) -> list[dict[str, float]]:
    """Calibration curve as rows, so a human can see where a calibrator helps
    or hurts rather than trusting one aggregate number."""
    labels = np.asarray(labels, dtype=int)
    scores = np.asarray(scores, dtype=float)
    weights = (
        np.ones_like(scores) if weights is None else np.asarray(weights, dtype=float)
    )
    edges = np.linspace(0.0, 1.0, bins + 1)
    index = np.clip(np.digitize(scores, edges[1:-1], right=False), 0, bins - 1)
    rows = []
    for bucket in range(bins):
        mask = index == bucket
        mass = float(weights[mask].sum())
        rows.append(
            {
                "bin_low": round(float(edges[bucket]), 3),
                "bin_high": round(float(edges[bucket + 1]), 3),
                "weight": round(mass, 4),
                "mean_predicted": (
                    round(float(np.average(scores[mask], weights=weights[mask])), 4)
                    if mass > 0
                    else None
                ),
                "observed_rate": (
                    round(float(np.average(labels[mask], weights=weights[mask])), 4)
                    if mass > 0
                    else None
                ),
            }
        )
    return rows
