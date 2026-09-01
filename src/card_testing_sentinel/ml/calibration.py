"""Calibration options, compared rather than assumed.

Raw model scores are a perfectly acceptable answer. The output is called a
*risk score*, not a probability of fraud, so calibration only earns its place
if it measurably improves Brier / ECE / log loss without costing ranking
quality. It is fitted on out-of-fold training predictions -- never on the
validation split it will be judged on.
"""

from __future__ import annotations

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

METHODS = ("none", "sigmoid", "isotonic")


def fit_calibrator(method: str, scores, labels, weights, seed: int = 0):
    scores = np.clip(np.asarray(scores, dtype=float), 1e-9, 1 - 1e-9)
    if method == "none":
        return None
    if method == "sigmoid":
        model = LogisticRegression(C=1e6, max_iter=1000, random_state=seed)
        model.fit(scores.reshape(-1, 1), labels, sample_weight=weights)
        return model
    if method == "isotonic":
        model = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        model.fit(scores, labels, sample_weight=weights)
        return model
    raise ValueError(f"unknown calibration method: {method}")


def apply_calibrator(method: str, calibrator, scores) -> np.ndarray:
    scores = np.asarray(scores, dtype=float)
    if method == "none":
        return scores
    if method == "sigmoid":
        return np.asarray(
            calibrator.predict_proba(scores.reshape(-1, 1))[:, 1], dtype=float
        )
    return np.clip(np.asarray(calibrator.predict(scores), dtype=float), 0.0, 1.0)
