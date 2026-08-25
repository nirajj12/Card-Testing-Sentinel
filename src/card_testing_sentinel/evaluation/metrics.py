"""Device-weighted row metrics with explicit units."""

from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, confusion_matrix, roc_auc_score


def classification_metrics(
    y_true: pd.Series | np.ndarray,
    scores: np.ndarray,
    threshold: float,
    weights: np.ndarray,
    *,
    ranking: bool = True,
) -> dict[str, float]:
    y = np.asarray(y_true, dtype=int)
    predicted = np.asarray(scores) >= threshold
    tn, fp, fn, tp = confusion_matrix(
        y, predicted, labels=[0, 1], sample_weight=weights
    ).ravel()
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    result = {
        "threshold": float(threshold),
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(2 * precision * recall / (precision + recall))
        if precision + recall
        else 0.0,
        "false_positive_rate": float(fp / (fp + tn)) if fp + tn else 0.0,
        "false_negative_rate": float(fn / (fn + tp)) if fn + tp else 0.0,
        "true_negative_weight": float(tn),
        "false_positive_weight": float(fp),
        "false_negative_weight": float(fn),
        "true_positive_weight": float(tp),
        "predicted_positive_rate": float(np.average(predicted, weights=weights)),
    }
    if ranking:
        result["average_precision"] = float(
            average_precision_score(y, scores, sample_weight=weights)
        )
        result["roc_auc"] = float(roc_auc_score(y, scores, sample_weight=weights))
    return result


def subgroup_metrics(
    metadata: pd.DataFrame,
    y: pd.Series,
    scores: np.ndarray,
    threshold: float,
    weights: np.ndarray,
) -> dict[str, Any]:
    predicted = scores >= threshold
    output: dict[str, Any] = {}
    legitimate_groups = {
        "normal_false_positive_rate": metadata["population"].eq("normal"),
        "flash_sale_false_positive_rate": metadata["population"].eq("flash_sale"),
        "flash_hard_retry_false_positive_rate": metadata["scenario_tag"].eq(
            "flash_hard_retry"
        ),
        "normal_bad_luck_false_positive_rate": metadata["scenario_tag"].eq(
            "normal_bad_luck"
        ),
    }
    for name, mask in legitimate_groups.items():
        mask = mask.fillna(False).to_numpy(dtype=bool)
        denominator = weights[mask].sum()
        output[name] = (
            float(weights[mask & predicted].sum() / denominator)
            if denominator
            else None
        )
    for subtype in ("burst", "evasive", "patient"):
        mask = metadata["attack_subtype"].eq(subtype).fillna(False).to_numpy(dtype=bool)
        denominator = weights[mask].sum()
        output[f"{subtype}_row_recall"] = (
            float(weights[mask & predicted].sum() / denominator)
            if denominator
            else None
        )
    return output
