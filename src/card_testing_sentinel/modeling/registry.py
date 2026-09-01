"""Validated selection of the frozen active runtime stack."""

from __future__ import annotations

import json
import platform
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import sklearn

from card_testing_sentinel.common.config import load_config
from card_testing_sentinel.features.specification_v2 import (
    FEATURE_CONTRACT_V2_VERSION,
    MODEL_FEATURES_V2,
    MODEL_FEATURES_V2_SHA256,
    validate_feature_contract_v2,
)
from card_testing_sentinel.modeling.model import RiskModel


class RuntimeManifestError(RuntimeError):
    """The selected stack is internally inconsistent."""


def _json(path: Path) -> dict:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise RuntimeManifestError(f"runtime artifact must be an object: {path}")
    return payload


@dataclass
class ArtifactRegistry:
    root: Path
    runtime: dict
    model: RiskModel
    model_metadata: dict
    policy: dict
    policy_mode: str
    feature_contract_version: str
    feature_contract_sha256: str
    feature_count: int
    model_stage: str
    policy_stage: str
    policy_version: str
    evaluation: dict

    @classmethod
    def load(cls, root: Path, *, manifest_path: Path | None = None) -> ArtifactRegistry:
        validate_feature_contract_v2()
        selected_path = manifest_path or root / "configs/runtime.yaml"
        runtime = load_config(selected_path)["runtime"]

        expected = {
            "feature_contract_version": FEATURE_CONTRACT_V2_VERSION,
            "feature_contract_sha256": MODEL_FEATURES_V2_SHA256,
            "feature_count": len(MODEL_FEATURES_V2),
        }
        for field, value in expected.items():
            if runtime.get(field) != value:
                raise RuntimeManifestError(
                    f"runtime {field} does not match Feature Contract v2"
                )

        contract = _json(root / runtime["feature_contract_artifact_path"])
        if tuple(contract.get("model_features", ())) != MODEL_FEATURES_V2:
            raise RuntimeManifestError("feature-contract artifact order does not match")
        if contract.get("feature_contract_sha256") != MODEL_FEATURES_V2_SHA256:
            raise RuntimeManifestError("feature-contract artifact hash does not match")

        metadata = _json(root / runtime["model_metadata_path"])
        metadata_checks = {
            "model_version": runtime["model_version"],
            "feature_contract_version": runtime["feature_contract_version"],
            "feature_contract_sha256": runtime["feature_contract_sha256"],
            "feature_count": runtime["feature_count"],
        }
        for field, value in metadata_checks.items():
            if metadata.get(field) != value:
                raise RuntimeManifestError(f"model metadata {field} does not match")

        policy_config = load_config(root / runtime["policy_config_path"])["policy"]
        policy_artifact = _json(root / runtime["policy_artifact_path"])
        if policy_config.get("version") != runtime["policy_version"]:
            raise RuntimeManifestError("policy config version does not match runtime")
        if policy_config.get("family") != runtime["policy_family"]:
            raise RuntimeManifestError("policy config family does not match runtime")
        for field, value in policy_config.items():
            if field in policy_artifact and policy_artifact[field] != value:
                raise RuntimeManifestError(f"policy artifact {field} does not match")

        evaluation = _json(root / runtime["evaluation_metrics_path"])
        consumption = _json(root / runtime["evaluation_consumption_path"])
        if not evaluation.get("evaluated") or not consumption.get("consumed"):
            raise RuntimeManifestError("Blind v2 is not recorded as consumed")
        if evaluation.get("model_version") != runtime["model_version"]:
            raise RuntimeManifestError("evaluation model version does not match")
        if evaluation.get("feature_count") != runtime["feature_count"]:
            raise RuntimeManifestError("evaluation feature count does not match")

        model = RiskModel.load(
            root,
            artifact_path=runtime["model_artifact_path"],
            expected_feature_names=MODEL_FEATURES_V2,
            expected_feature_contract_sha256=MODEL_FEATURES_V2_SHA256,
        )
        return cls(
            root=root,
            runtime=runtime,
            model=model,
            model_metadata=metadata,
            policy=policy_config,
            policy_mode="model_and_rules" if model.available else "degraded_rules_only",
            feature_contract_version=FEATURE_CONTRACT_V2_VERSION,
            feature_contract_sha256=MODEL_FEATURES_V2_SHA256,
            feature_count=len(MODEL_FEATURES_V2),
            model_stage=(
                "frozen_blind_evaluated_v2" if model.available else "unavailable"
            ),
            policy_stage="frozen_validation_selected",
            policy_version=str(policy_config["version"]),
            evaluation=evaluation,
        )

    def system_summary(self) -> dict:
        return {
            "active_runtime_version": self.runtime["version"],
            "model_status": self.model.status,
            "policy_mode": self.policy_mode,
            "feature_contract_version": self.feature_contract_version,
            "feature_contract_sha256": self.feature_contract_sha256,
            "feature_count": self.feature_count,
            "model": self.model.description,
            "model_version": self.runtime["model_version"],
            "model_family": self.model_metadata["selected_family"],
            "calibration": self.model_metadata["selected_calibration"],
            "model_stage": self.model_stage,
            "policy_stage": self.policy_stage,
            "policy_version": self.policy_version,
            "policy_family": self.policy["family"],
            "blind_evaluated": True,
            "evaluation_version": self.runtime["evaluation_version"],
            "evaluation_status": self.evaluation["status"],
            "evaluation_consumed": True,
            "evaluation_verdict": self.evaluation["verdict"],
            "environment": {
                "python": sys.version.split()[0],
                "numpy": np.__version__,
                "scikit_learn": sklearn.__version__,
                "platform": platform.system(),
            },
            "synthetic_demonstration": True,
        }
