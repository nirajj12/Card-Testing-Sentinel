import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression


def fit_calibrator(method: str, probabilities, labels, sample_weight):
    probabilities = np.clip(np.asarray(probabilities, dtype=float), 1e-9, 1 - 1e-9)
    if method == "none":
        return None
    if method == "sigmoid":
        calibrator = LogisticRegression(C=1e6, max_iter=500, random_state=20260825)
        calibrator.fit(probabilities.reshape(-1, 1), labels, sample_weight=sample_weight)
        return calibrator
    if method == "isotonic":
        calibrator = IsotonicRegression(out_of_bounds="clip")
        calibrator.fit(probabilities, labels, sample_weight=sample_weight)
        return calibrator
    raise ValueError(f"unknown calibration method: {method}")


def apply_calibrator(method: str, calibrator, probabilities) -> np.ndarray:
    probabilities = np.asarray(probabilities, dtype=float)
    if method == "none":
        return probabilities
    if method == "sigmoid":
        return calibrator.predict_proba(probabilities.reshape(-1, 1))[:, 1]
    return np.asarray(calibrator.predict(probabilities), dtype=float)
