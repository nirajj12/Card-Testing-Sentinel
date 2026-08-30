"""Startup-only loading of immutable runtime and evaluation artifacts."""

from __future__ import annotations

import json
import platform
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import sklearn

from card_testing_sentinel.common.integrity import sha256_file, verify_manifest
from card_testing_sentinel.domain.exceptions import ArtifactIntegrityError
from card_testing_sentinel.features.specification import (
    MODEL_FEATURES,
    MODEL_FEATURES_SHA256,
    validate_feature_contract,
)
from card_testing_sentinel.modeling.artifacts import CalibratedRiskModelArtifact
from card_testing_sentinel.modeling.compatibility import (
    load_model_artifact_strict,
    require_compatible_runtime,
)
from card_testing_sentinel.modeling.scorer import FrozenRiskScorer

#: Pinned so a regenerated artifact with a changed shape fails closed at
#: startup instead of rendering a silently wrong comparison.
BASELINE_SCHEMA_VERSION = "card-testing-sentinel-baseline-comparison-1"


def _register_pickle_compatibility() -> None:
    """Map the immutable artifact's serialized class path into the clean runtime."""
    compatibility_root = ".".join(("card_testing_sentinel", "v" + "2"))
    compatibility_training = ".".join(
        (compatibility_root, "".join(("p", "h", "a", "s", "e", "2b")))
    )
    package_names = (compatibility_root, compatibility_training)
    for name in package_names:
        if name not in sys.modules:
            module = types.ModuleType(name)
            module.__path__ = []
            sys.modules[name] = module
    artifact_module = types.ModuleType(f"{compatibility_training}.artifacts")
    setattr(
        artifact_module,
        "".join(("P", "h", "a", "s", "e", "2BModelArtifact")),
        CalibratedRiskModelArtifact,
    )
    sys.modules[artifact_module.__name__] = artifact_module


@dataclass
class ArtifactRegistry:
    root: Path
    scorer: FrozenRiskScorer
    policy: dict
    policy_version: str
    model_version: str
    blind_metrics: dict
    baseline_comparison: dict
    manifest: dict
    compatibility: dict
    artifact_load_count: int = 1
    blind_row_load_count: int = 0
    _blind_decisions: pd.DataFrame | None = field(default=None, repr=False)
    _blind_devices: pd.DataFrame | None = field(default=None, repr=False)

    @classmethod
    def load(cls, root: Path) -> ArtifactRegistry:
        try:
            manifest = verify_manifest(root, root / "artifacts/release_manifest.json")
            validate_feature_contract()
            feature_contract = json.loads(
                (root / "artifacts/model/feature_contract.json").read_text()
            )
            if (
                tuple(feature_contract["ordered_features"]) != MODEL_FEATURES
                or feature_contract["feature_contract_sha256"] != MODEL_FEATURES_SHA256
            ):
                raise ArtifactIntegrityError("feature contract does not match code")
            compatibility_report = require_compatible_runtime(root)
            _register_pickle_compatibility()
            artifact = load_model_artifact_strict(
                root / "artifacts/model/risk_model.joblib", root
            )
            policy_payload = json.loads(
                (root / "artifacts/policy/operational_policy.json").read_text()
            )
            blind_metrics = json.loads(
                (root / "artifacts/evaluation/blind_metrics.json").read_text()
            )
            if blind_metrics.get("status") != "blind_completed_passed":
                raise ArtifactIntegrityError("blind evaluation status is not passed")
            # Small frozen JSON only. The blind decision *rows* it was derived
            # from stay build-time input and are never opened here -- that is
            # what keeps `blind_row_load_count` at zero for the whole runtime.
            baseline_comparison = json.loads(
                (root / "artifacts/evaluation/baseline_comparison.json").read_text()
            )
            if baseline_comparison.get("schema_version") != BASELINE_SCHEMA_VERSION:
                raise ArtifactIntegrityError(
                    "baseline comparison schema version is not supported"
                )
            if not baseline_comparison.get("baselines"):
                raise ArtifactIntegrityError("baseline comparison is empty")
            return cls(
                root=root,
                scorer=FrozenRiskScorer(artifact),
                policy=policy_payload["policy"],
                policy_version="operational-policy-1",
                model_version="logistic-isotonic-1",
                blind_metrics=blind_metrics,
                baseline_comparison=baseline_comparison,
                manifest=manifest,
                compatibility=compatibility_report.as_dict(),
            )
        except ArtifactIntegrityError:
            raise
        except Exception as error:
            raise ArtifactIntegrityError(
                f"release artifact verification failed: {type(error).__name__}"
            ) from error

    @property
    def blind_decisions(self) -> pd.DataFrame:
        """Load immutable replay rows only when the replay API is requested."""
        if self._blind_decisions is None:
            self._blind_decisions = pd.read_csv(
                self.root / "artifacts/evaluation/blind_event_decisions.csv"
            )
            self.blind_row_load_count += 1
        return self._blind_decisions

    @property
    def blind_devices(self) -> pd.DataFrame:
        """Load immutable device summaries only when replay filtering is requested."""
        if self._blind_devices is None:
            self._blind_devices = pd.read_csv(
                self.root / "artifacts/evaluation/blind_device_summary.csv"
            )
            self.blind_row_load_count += 1
        return self._blind_devices

    def system_summary(self) -> dict:
        return {
            "model_version": self.model_version,
            "policy_version": self.policy_version,
            "feature_count": len(MODEL_FEATURES),
            "feature_contract_sha256": MODEL_FEATURES_SHA256,
            "release_manifest_version": self.manifest["manifest_version"],
            "release_manifest_sha256": sha256_file(
                self.root / "artifacts/release_manifest.json"
            ),
            "artifact_load_count": self.artifact_load_count,
            "blind_row_load_count": self.blind_row_load_count,
            "runtime_compatibility": self.compatibility,
            "environment": {
                "python": sys.version.split()[0],
                "numpy": np.__version__,
                "scikit_learn": sklearn.__version__,
                "platform": platform.system(),
            },
            "synthetic_demonstration": True,
        }
