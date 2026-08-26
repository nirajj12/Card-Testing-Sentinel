"""Startup-only verification and loading of frozen Phase 2C/3 artifacts."""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn

from card_testing_sentinel.v2.phase2b.features import (
    MODEL_FEATURE_COLUMNS,
    MODEL_FEATURE_COLUMNS_SHA256,
    validate_model_feature_contract,
)
from card_testing_sentinel.v2.phase2b.validation_policy import OptimizedFrozenScorer
from card_testing_sentinel.v2.phase3.evaluation import verify_final_manifest
from card_testing_sentinel.v2.phase3.lifecycle import (
    refuse_if_scoring_accessed,
    verify_dataset_manifest,
    verify_lifecycle,
    verify_pre_access_freeze,
)
from card_testing_sentinel.v2.phase4.exceptions import ArtifactIntegrityError

POLICY_SHA256 = "9afeba2df176c87287e86ff0402ef96b58e9386608d003b5702986be02b6ae95"
MODEL_SHA256 = "6c638fc05ca321e98c8b5417c477a58e2649bdd7e056bcd56e0d119d3eb80f88"
PHASE3_MANIFEST_SHA256 = (
    "3061aa3ba797a79289af49febc2970074b85f7e2becfddd3c964af9a2348e7aa"
)
PHASE3_FREEZE_SHA256 = (
    "4bbf4e1ba8ec7a4423097c72bf69a4ae6bf27cef8eada5079b7be4f5f985295d"
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass
class ArtifactRegistry:
    root: Path
    scorer: OptimizedFrozenScorer
    policy: dict
    policy_version: str
    model_version: str
    blind_metrics: dict
    blind_decisions: pd.DataFrame
    blind_devices: pd.DataFrame
    artifact_load_count: int = 1

    @classmethod
    def load(cls, root: Path) -> ArtifactRegistry:
        try:
            expected = {
                "artifacts/v2/phase2b/training/models/selected_model.joblib": (
                    MODEL_SHA256
                ),
                "artifacts/v2/phase2c/confirmation/frozen_operational_policy.json": (
                    POLICY_SHA256
                ),
                "artifacts/v2/phase3/blind/pre_access_freeze.json": (
                    PHASE3_FREEZE_SHA256
                ),
                "artifacts/v2/phase3/blind/final_hash_manifest.json": (
                    PHASE3_MANIFEST_SHA256
                ),
            }
            for relative, digest in expected.items():
                path = root / relative
                if not path.is_file() or sha256_file(path) != digest:
                    raise ArtifactIntegrityError(
                        f"protected artifact drift: {relative}"
                    )
            verify_pre_access_freeze(root)
            verify_dataset_manifest(root)
            verify_lifecycle(root, "post_scoring")
            verify_final_manifest(root)
            try:
                refuse_if_scoring_accessed(root)
            except PermissionError:
                pass
            else:
                raise ArtifactIntegrityError("Phase 3 blind rerun guard is not closed")
            validate_model_feature_contract()
            if len(MODEL_FEATURE_COLUMNS) != 44:
                raise ArtifactIntegrityError("frozen feature count is not 44")
            contract = json.loads(
                (
                    root
                    / "artifacts/v2/phase2b/training/models/model_feature_contract.json"
                ).read_text()
            )
            if (
                contract.get("feature_contract_sha256") != MODEL_FEATURE_COLUMNS_SHA256
                or tuple(contract.get("ordered_features", ())) != MODEL_FEATURE_COLUMNS
            ):
                raise ArtifactIntegrityError("frozen feature contract drift")
            artifact = joblib.load(
                root / "artifacts/v2/phase2b/training/models/selected_model.joblib"
            )
            scorer = OptimizedFrozenScorer(artifact)
            policy_payload = json.loads(
                (
                    root
                    / "artifacts/v2/phase2c/confirmation/frozen_operational_policy.json"
                ).read_text()
            )
            if policy_payload["policy"].get("candidate_id") != "phase2c_002":
                raise ArtifactIntegrityError("unexpected frozen operational policy")
            blind_metrics = json.loads(
                (
                    root / "artifacts/v2/phase3/blind/final_blind_metrics.json"
                ).read_text()
            )
            if blind_metrics.get("status") != "blind_completed_passed":
                raise ArtifactIntegrityError("blind result is not completed and passed")
            return cls(
                root=root,
                scorer=scorer,
                policy=policy_payload["policy"],
                policy_version=policy_payload["version"],
                model_version="phase2b-logistic-regression-02-isotonic",
                blind_metrics=blind_metrics,
                blind_decisions=pd.read_csv(
                    root / "artifacts/v2/phase3/blind/final_blind_event_decisions.csv"
                ),
                blind_devices=pd.read_csv(
                    root / "artifacts/v2/phase3/blind/final_blind_device_summary.csv"
                ),
            )
        except ArtifactIntegrityError:
            raise
        except Exception as error:
            raise ArtifactIntegrityError(
                f"frozen artifact startup verification failed: {type(error).__name__}"
            ) from error

    def system_summary(self) -> dict:
        return {
            "model_version": self.model_version,
            "policy_version": self.policy_version,
            "feature_count": len(MODEL_FEATURE_COLUMNS),
            "feature_contract_sha256": MODEL_FEATURE_COLUMNS_SHA256,
            "model_sha256": MODEL_SHA256,
            "policy_sha256": POLICY_SHA256,
            "phase3_final_manifest_sha256": PHASE3_MANIFEST_SHA256,
            "artifact_load_count": self.artifact_load_count,
            "environment": {
                "python": sys.version.split()[0],
                "numpy": np.__version__,
                "scikit_learn": sklearn.__version__,
                "platform": platform.system(),
            },
            "synthetic_demonstration": True,
        }
