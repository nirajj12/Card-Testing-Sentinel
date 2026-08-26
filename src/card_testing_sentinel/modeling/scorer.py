"""Low-allocation scorer for the frozen logistic model and calibrator."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.special import expit

from card_testing_sentinel.features.specification import MODEL_FEATURES


class FrozenRiskScorer:
    def __init__(self, artifact):
        self.artifact = artifact
        model = artifact.base_model
        numeric = model.named_steps["preprocessing"].named_transformers_["numeric"]
        self.imputer = np.asarray(
            numeric.named_steps["imputer"].statistics_, dtype=float
        )
        scaler = numeric.named_steps["scaler"]
        self.mean = np.asarray(scaler.mean_, dtype=float)
        self.scale = np.asarray(scaler.scale_, dtype=float)
        classifier = model.named_steps["classifier"]
        self.coefficients = np.asarray(classifier.coef_[0], dtype=float)
        self.intercept = float(classifier.intercept_[0])
        self.calibration_method = artifact.calibration_method
        if self.calibration_method == "isotonic":
            self.isotonic_x = np.asarray(artifact.calibrator.X_thresholds_, dtype=float)
            self.isotonic_y = np.asarray(artifact.calibrator.y_thresholds_, dtype=float)

    def score_array(self, values: np.ndarray) -> tuple[float, float]:
        values = np.asarray(values, dtype=float)
        values = np.where(np.isnan(values), self.imputer, values)
        raw_score = float(
            expit(
                np.dot((values - self.mean) / self.scale, self.coefficients)
                + self.intercept
            )
        )
        if self.calibration_method == "none":
            return raw_score, raw_score
        if self.calibration_method == "sigmoid":
            risk_score = float(
                self.artifact.calibrator.predict_proba(np.asarray([[raw_score]]))[:, 1][
                    0
                ]
            )
        else:
            risk_score = float(np.interp(raw_score, self.isotonic_x, self.isotonic_y))
        return raw_score, risk_score

    def score_snapshot(self, snapshot: dict) -> tuple[float, float]:
        return self.score_array(
            np.fromiter(
                (snapshot[name] for name in MODEL_FEATURES),
                dtype=float,
                count=len(MODEL_FEATURES),
            )
        )

    def verify_parity(self, frame: pd.DataFrame, tolerance: float = 1e-12) -> dict:
        optimized = np.asarray(
            [self.score_array(row) for row in frame.loc[:, MODEL_FEATURES].to_numpy()]
        )
        expected_raw = self.artifact.predict_raw_proba(frame)
        expected_risk = self.artifact.predict_proba(frame)
        raw_difference = float(
            np.max(np.abs(optimized[:, 0] - expected_raw), initial=0)
        )
        risk_difference = float(
            np.max(np.abs(optimized[:, 1] - expected_risk), initial=0)
        )
        maximum = max(raw_difference, risk_difference)
        if maximum > tolerance:
            raise RuntimeError(f"frozen scorer parity failed: {maximum}")
        return {
            "rows": len(frame),
            "raw_maximum_absolute_difference": raw_difference,
            "risk_maximum_absolute_difference": risk_difference,
            "maximum_absolute_difference": maximum,
            "tolerance": tolerance,
            "passed": True,
        }
