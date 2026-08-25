import math

import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    f1_score,
    log_loss,
    precision_score,
    recall_score,
    roc_auc_score,
)


def expected_calibration_error(
    labels: np.ndarray, probabilities: np.ndarray, weights: np.ndarray, bins: int = 10
) -> float:
    edges = np.linspace(0.0, 1.0, bins + 1)
    indexes = np.minimum(np.digitize(probabilities, edges[1:-1]), bins - 1)
    total = weights.sum()
    value = 0.0
    for index in range(bins):
        mask = indexes == index
        if not mask.any():
            continue
        mass = weights[mask].sum()
        confidence = np.average(probabilities[mask], weights=weights[mask])
        observed = np.average(labels[mask], weights=weights[mask])
        value += mass / total * abs(confidence - observed)
    return float(value)


def reliability_table(labels, probabilities, weights, bins: int = 10) -> pd.DataFrame:
    edges = np.linspace(0.0, 1.0, bins + 1)
    indexes = np.minimum(np.digitize(probabilities, edges[1:-1]), bins - 1)
    rows = []
    for index in range(bins):
        mask = indexes == index
        rows.append(
            {
                "bin": index,
                "lower": edges[index],
                "upper": edges[index + 1],
                "rows": int(mask.sum()),
                "weight": float(weights[mask].sum()),
                "mean_probability": float(np.average(probabilities[mask], weights=weights[mask])) if mask.any() else math.nan,
                "observed_rate": float(np.average(labels[mask], weights=weights[mask])) if mask.any() else math.nan,
            }
        )
    return pd.DataFrame(rows)


def probability_metrics(labels, probabilities, weights, threshold=None) -> dict:
    labels = np.asarray(labels, dtype=int)
    probabilities = np.clip(np.asarray(probabilities, dtype=float), 1e-12, 1 - 1e-12)
    result = {
        "pr_auc": float(average_precision_score(labels, probabilities, sample_weight=weights)),
        "roc_auc": float(roc_auc_score(labels, probabilities, sample_weight=weights)),
        "brier": float(brier_score_loss(labels, probabilities, sample_weight=weights)),
        "log_loss": float(log_loss(labels, probabilities, sample_weight=weights)),
        "ece_10": expected_calibration_error(labels, probabilities, weights, 10),
    }
    if threshold is not None:
        predicted = probabilities >= threshold
        result.update(
            threshold=float(threshold),
            precision=float(precision_score(labels, predicted, sample_weight=weights, zero_division=0)),
            recall=float(recall_score(labels, predicted, sample_weight=weights, zero_division=0)),
            f1=float(f1_score(labels, predicted, sample_weight=weights, zero_division=0)),
        )
    return result


def wilson_interval(numerator: int, denominator: int, z: float = 1.96) -> tuple[float, float]:
    if denominator == 0:
        return math.nan, math.nan
    p = numerator / denominator
    denominator_term = 1 + z * z / denominator
    center = (p + z * z / (2 * denominator)) / denominator_term
    half = z * math.sqrt((p * (1 - p) + z * z / (4 * denominator)) / denominator) / denominator_term
    return center - half, center + half

