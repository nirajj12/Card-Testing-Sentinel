"""Serializable calibrated-risk-model contract."""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from card_testing_sentinel.features.specification import MODEL_FEATURES


@dataclass
class CalibratedRiskModelArtifact:
    base_model: object
    calibrator: object | None
    calibration_method: str
    family: str
    parameters: dict

    def predict_raw_proba(self, frame: pd.DataFrame) -> np.ndarray:
        values = frame.loc[:, MODEL_FEATURES]
        return np.asarray(self.base_model.predict_proba(values)[:, 1], dtype=float)

    def predict_proba(self, frame: pd.DataFrame) -> np.ndarray:
        raw = self.predict_raw_proba(frame)
        if self.calibration_method == "none":
            return raw
        if self.calibration_method == "sigmoid":
            return self.calibrator.predict_proba(raw.reshape(-1, 1))[:, 1]
        return np.asarray(self.calibrator.predict(raw), dtype=float)
