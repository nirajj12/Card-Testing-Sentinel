"""Deterministic operating points under legitimate false-positive budgets."""

import numpy as np
import pandas as pd

from card_testing_sentinel.evaluation.metrics import classification_metrics


def select_operating_point(
    y_true: pd.Series | np.ndarray,
    scores: np.ndarray,
    weights: np.ndarray,
    budget: float,
) -> dict[str, float | bool]:
    y = np.asarray(y_true, dtype=int)
    scores = np.asarray(scores, dtype=float)
    thresholds = np.r_[np.inf, np.sort(np.unique(scores))[::-1]]
    candidates = []
    for threshold in thresholds:
        metrics = classification_metrics(
            y, scores, float(threshold), weights, ranking=False
        )
        if metrics["false_positive_rate"] <= budget + 1e-12:
            candidates.append(metrics)
    nontrivial = [item for item in candidates if item["predicted_positive_rate"] > 0]
    if not nontrivial:
        return {"feasible": False, "budget": float(budget), "threshold": float("inf")}
    chosen = max(
        nontrivial,
        key=lambda item: (item["recall"], item["precision"], item["threshold"]),
    )
    return {"feasible": True, "budget": float(budget), **chosen}
