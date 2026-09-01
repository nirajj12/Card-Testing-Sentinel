"""Risk model wrapper.

Loads the frozen development artifact and scores one ordered feature vector.
The artifact carries the feature-contract hash it was trained against, and
loading refuses to proceed on a mismatch: serving a model against a contract
it never saw would silently reorder its inputs.

If the artifact is missing or unusable the runtime enters an explicit,
clearly named ``degraded_rules_only`` mode rather than pretending to have a
score. That mode is a failover, not a normal path -- it is surfaced in
``/api/system`` and tested separately.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from card_testing_sentinel.features.specification import (
    MODEL_FEATURES,
    MODEL_FEATURES_SHA256,
)

ARTIFACT_PATH = "artifacts/model/risk_model.joblib"

READY = "ready"
DEGRADED = "degraded_rules_only"


class ModelContractError(RuntimeError):
    """The artifact on disk was trained against a different feature contract."""


class RiskModel:
    def __init__(self, status: str, artifact=None, degraded_reason: str | None = None):
        self.status = status
        self._artifact = artifact
        self.degraded_reason = degraded_reason

    @classmethod
    def load(
        cls,
        root: Path,
        *,
        artifact_path: str = ARTIFACT_PATH,
        expected_feature_names: tuple[str, ...] = MODEL_FEATURES,
        expected_feature_contract_sha256: str = MODEL_FEATURES_SHA256,
        allow_degraded: bool = True,
    ) -> RiskModel:
        """Load an artifact against an explicitly selected ordered contract.

        The v1 defaults remain available to historical callers. The active
        registry supplies every selector from the runtime manifest.
        """
        path = root / artifact_path
        if not path.is_file():
            return cls._degrade("no trained model artifact is present", allow_degraded)
        try:
            import joblib

            artifact = joblib.load(path)
        except Exception as error:  # pragma: no cover - environment dependent
            return cls._degrade(
                f"model artifact failed to load: {type(error).__name__}", allow_degraded
            )
        recorded = getattr(artifact, "feature_contract_sha256", None)
        if recorded != expected_feature_contract_sha256:
            raise ModelContractError(
                "model artifact was trained against a different feature "
                f"contract ({recorded} != {expected_feature_contract_sha256})"
            )
        if tuple(getattr(artifact, "feature_names", ())) != expected_feature_names:
            raise ModelContractError("model artifact feature order does not match")
        model = cls(READY, artifact=artifact)
        model.feature_names = expected_feature_names
        return model

    @classmethod
    def _degrade(cls, reason: str, allow_degraded: bool) -> RiskModel:
        if not allow_degraded:
            raise ModelContractError(reason)
        return cls(DEGRADED, degraded_reason=reason)

    @property
    def available(self) -> bool:
        return self.status == READY and self._artifact is not None

    @property
    def description(self) -> dict:
        if not self.available:
            return {"status": self.status, "reason": self.degraded_reason}
        return {
            "status": self.status,
            "family": self._artifact.family,
            "calibration": self._artifact.calibration_method,
        }

    def score(self, snapshot: dict[str, float]) -> float | None:
        """Score one causal snapshot. Returns None only in degraded mode."""
        if not self.available:
            return None
        values = np.fromiter(
            (snapshot[name] for name in self.feature_names),
            dtype=float,
            count=len(self.feature_names),
        )
        return self._artifact.score_vector(values)
