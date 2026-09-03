"""Validated selection of a frozen runtime stack.

The historical v2 manifest remains the default for explicit historical tools.
The application selects its active manifest through ``configs/app.yaml``.
"""

from __future__ import annotations

import json
import platform
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import sklearn

from card_testing_sentinel.common.config import load_config
from card_testing_sentinel.common.integrity import sha256_file
from card_testing_sentinel.features.engine_v2 import FeatureEngineV2
from card_testing_sentinel.features.engine_v3 import FeatureEngineV3
from card_testing_sentinel.features.specification_v2 import (
    FEATURE_CONTRACT_V2_VERSION,
    MODEL_FEATURES_V2,
    MODEL_FEATURES_V2_SHA256,
    validate_feature_contract_v2,
)
from card_testing_sentinel.features.specification_v3 import (
    FEATURE_CONTRACT_V3_VERSION,
    MODEL_FEATURES_V3,
    MODEL_FEATURES_V3_SHA256,
    validate_feature_contract_v3,
)
from card_testing_sentinel.modeling.model import RiskModel


class RuntimeManifestError(RuntimeError):
    """The selected stack is internally inconsistent."""


def _json(path: Path) -> dict:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise RuntimeManifestError(f"runtime artifact must be an object: {path}")
    return payload


def _require_equal(actual: Any, expected: Any, message: str) -> None:
    if actual != expected:
        raise RuntimeManifestError(message)


def _require_hash(root: Path, relative_path: str, expected: str, label: str) -> None:
    path = root / relative_path
    if not path.is_file():
        raise RuntimeManifestError(f"required {label} is missing: {relative_path}")
    if sha256_file(path) != expected:
        raise RuntimeManifestError(f"{label} hash does not match")


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
    feature_engine_class: type
    model_features: tuple[str, ...]
    model_family: str
    model_candidate: str | None
    calibration: str
    model_stage: str
    policy_stage: str
    policy_version: str
    evaluation: dict
    evaluation_consumed: bool
    evaluation_conclusion: str

    @classmethod
    def load(cls, root: Path, *, manifest_path: Path | None = None) -> ArtifactRegistry:
        """Load one explicitly selected frozen runtime and fail closed on drift."""
        selected_path = manifest_path or root / "configs/runtime.yaml"
        runtime = load_config(selected_path)["runtime"]
        version = runtime.get("version")
        if version == "frozen-v2-runtime":
            return cls._load_v2(root, runtime)
        if version == "postblind-v3.1-prototype-runtime":
            return cls._load_v3_1(root, runtime)
        raise RuntimeManifestError(f"unsupported runtime version: {version!r}")

    @classmethod
    def _load_v2(cls, root: Path, runtime: dict) -> ArtifactRegistry:
        validate_feature_contract_v2()
        for field, value in {
            "feature_contract_version": FEATURE_CONTRACT_V2_VERSION,
            "feature_contract_sha256": MODEL_FEATURES_V2_SHA256,
            "feature_count": len(MODEL_FEATURES_V2),
        }.items():
            _require_equal(
                runtime.get(field),
                value,
                f"runtime {field} does not match Feature Contract v2",
            )

        contract = _json(root / runtime["feature_contract_artifact_path"])
        _require_equal(
            tuple(contract.get("model_features", ())),
            MODEL_FEATURES_V2,
            "feature-contract artifact order does not match",
        )
        _require_equal(
            contract.get("feature_contract_sha256"),
            MODEL_FEATURES_V2_SHA256,
            "feature-contract artifact hash does not match",
        )

        metadata = _json(root / runtime["model_metadata_path"])
        for field in (
            "model_version",
            "feature_contract_version",
            "feature_contract_sha256",
            "feature_count",
        ):
            _require_equal(
                metadata.get(field),
                runtime[field],
                f"model metadata {field} does not match",
            )

        policy_config, evaluation, consumption = cls._shared_evidence(root, runtime)
        _require_equal(
            evaluation.get("evaluated"), True, "Blind v2 is not recorded as evaluated"
        )
        _require_equal(consumption.get("consumed"), True, "Blind v2 is not consumed")
        _require_equal(
            evaluation.get("model_version"),
            runtime["model_version"],
            "evaluation model version does not match",
        )
        _require_equal(
            evaluation.get("feature_count"),
            runtime["feature_count"],
            "evaluation feature count does not match",
        )

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
            feature_engine_class=FeatureEngineV2,
            model_features=MODEL_FEATURES_V2,
            model_family=str(metadata["selected_family"]),
            model_candidate=None,
            calibration=str(metadata["selected_calibration"]),
            model_stage="frozen_blind_evaluated_v2"
            if model.available
            else "unavailable",
            policy_stage="frozen_validation_selected",
            policy_version=str(policy_config["version"]),
            evaluation=evaluation,
            evaluation_consumed=True,
            evaluation_conclusion=str(evaluation["verdict"]),
        )

    @classmethod
    def _load_v3_1(cls, root: Path, runtime: dict) -> ArtifactRegistry:
        validate_feature_contract_v3()
        expected_runtime = {
            "runtime_stage": "evaluated_prototype_candidate",
            "production_ready": False,
            "synthetic_evaluation": True,
            "feature_contract_version": FEATURE_CONTRACT_V3_VERSION,
            "feature_contract_sha256": MODEL_FEATURES_V3_SHA256,
            "feature_count": len(MODEL_FEATURES_V3),
            "model_version": "model-v3.1",
            "model_family": "hist_gradient_boosting",
            "model_candidate": "hist_gb_2",
            "calibration": "sigmoid",
            "policy_version": "validation-selected-v2",
            "evaluation_version": "pbrss-v1",
            "evaluation_conclusion": "MIXED",
        }
        for field, value in expected_runtime.items():
            _require_equal(
                runtime.get(field), value, f"v3.1 runtime {field} does not match"
            )

        frozen_hashes = {
            "model artifact": ("model_artifact_path", "model_artifact_sha256"),
            "feature contract artifact": (
                "feature_contract_artifact_path",
                "feature_contract_artifact_sha256",
            ),
            "model metadata": ("model_metadata_path", "model_metadata_sha256"),
            "feature config": ("feature_spec_path", "feature_spec_sha256"),
            "policy artifact": ("policy_artifact_path", "policy_artifact_sha256"),
            "PBRSS result manifest": (
                "evaluation_result_manifest_path",
                "evaluation_result_manifest_sha256",
            ),
            "PBRSS freeze manifest": (
                "evaluation_freeze_manifest_path",
                "evaluation_freeze_manifest_sha256",
            ),
        }
        for label, (path_field, hash_field) in frozen_hashes.items():
            _require_hash(root, runtime[path_field], runtime[hash_field], label)

        contract = _json(root / runtime["feature_contract_artifact_path"])
        _require_equal(
            contract.get("version"),
            FEATURE_CONTRACT_V3_VERSION,
            "v3.1 contract version does not match",
        )
        _require_equal(
            contract.get("sha256"),
            MODEL_FEATURES_V3_SHA256,
            "v3.1 contract semantic hash does not match",
        )
        _require_equal(
            tuple(contract.get("features", ())),
            MODEL_FEATURES_V3,
            "v3.1 contract feature order does not match",
        )

        metadata = _json(root / runtime["model_metadata_path"])
        meta_contract = metadata.get("feature_contract", {})
        candidate = metadata.get("selected_candidate", {})
        calibration = metadata.get("calibration", {})
        checks = (
            (metadata.get("model_version"), "model-v3.1", "model metadata version"),
            (
                meta_contract.get("version"),
                FEATURE_CONTRACT_V3_VERSION,
                "model metadata contract version",
            ),
            (
                meta_contract.get("sha256"),
                MODEL_FEATURES_V3_SHA256,
                "model metadata contract hash",
            ),
            (
                meta_contract.get("feature_count"),
                len(MODEL_FEATURES_V3),
                "model metadata feature count",
            ),
            (
                tuple(meta_contract.get("features", ())),
                MODEL_FEATURES_V3,
                "model metadata feature order",
            ),
            (candidate.get("identifier"), "hist_gb_2", "model candidate"),
            (candidate.get("family"), "hist_gradient_boosting", "model family"),
            (
                tuple(candidate.get("fitted_features", ())),
                MODEL_FEATURES_V3,
                "model fitted feature order",
            ),
            (calibration.get("method"), "sigmoid", "model calibration"),
        )
        for actual, expected, label in checks:
            _require_equal(actual, expected, f"{label} does not match")
        _require_equal(
            candidate.get("parameters"),
            {
                "learning_rate": 0.08,
                "max_leaf_nodes": 31,
                "max_iter": 150,
                "l2_regularization": 2.0,
            },
            "model candidate parameters do not match",
        )

        policy_config, evaluation, consumption = cls._shared_evidence(root, runtime)
        _require_equal(
            consumption.get("freeze_manifest_sha256"),
            runtime["evaluation_freeze_manifest_sha256"],
            "PBRSS consumption freeze manifest hash does not match",
        )
        for field, value in {
            "status": "consumed",
            "consumed": True,
            "evaluated": True,
            "suite": "post-blind-remediation-stress-v1",
            "model": "model-v3.1",
            "model_hash": runtime["model_artifact_sha256"],
            "feature_contract": FEATURE_CONTRACT_V3_VERSION,
            "feature_contract_hash": runtime["feature_contract_artifact_sha256"],
            "policy": "validation-selected-v2",
            "policy_hash": runtime["policy_artifact_sha256"],
            "calibration": "sigmoid",
            "post_stress_tuning": False,
        }.items():
            _require_equal(
                consumption.get(field),
                value,
                f"PBRSS consumption {field} does not match",
            )

        result_manifest = _json(root / runtime["evaluation_result_manifest_path"])
        _require_equal(
            result_manifest.get("suite"),
            "post-blind-remediation-stress-v1",
            "PBRSS result suite does not match",
        )
        for relative_path, expected_hash in result_manifest.get("files", {}).items():
            _require_hash(
                root, relative_path, expected_hash, f"PBRSS result {relative_path}"
            )

        model = RiskModel.load(
            root,
            artifact_path=runtime["model_artifact_path"],
            expected_feature_names=MODEL_FEATURES_V3,
            expected_feature_contract_sha256=MODEL_FEATURES_V3_SHA256,
            allow_degraded=False,
        )
        artifact = model._artifact
        _require_equal(
            getattr(artifact, "family", None),
            "hist_gradient_boosting",
            "loaded model family does not match",
        )
        _require_equal(
            getattr(artifact, "calibration_method", None),
            "sigmoid",
            "loaded model calibration does not match",
        )

        return cls(
            root=root,
            runtime=runtime,
            model=model,
            model_metadata=metadata,
            policy=policy_config,
            policy_mode="model_and_rules",
            feature_contract_version=FEATURE_CONTRACT_V3_VERSION,
            feature_contract_sha256=MODEL_FEATURES_V3_SHA256,
            feature_count=len(MODEL_FEATURES_V3),
            feature_engine_class=FeatureEngineV3,
            model_features=MODEL_FEATURES_V3,
            model_family="hist_gradient_boosting",
            model_candidate="hist_gb_2",
            calibration="sigmoid",
            model_stage="evaluated_prototype_candidate",
            policy_stage="frozen_validation_selected",
            policy_version=str(policy_config["version"]),
            evaluation=evaluation,
            evaluation_consumed=True,
            evaluation_conclusion="MIXED",
        )

    @staticmethod
    def _shared_evidence(root: Path, runtime: dict) -> tuple[dict, dict, dict]:
        policy_config = load_config(root / runtime["policy_config_path"])["policy"]
        policy_artifact = _json(root / runtime["policy_artifact_path"])
        _require_equal(
            policy_config.get("version"),
            runtime["policy_version"],
            "policy config version does not match runtime",
        )
        _require_equal(
            policy_config.get("family"),
            runtime["policy_family"],
            "policy config family does not match runtime",
        )
        for field, value in policy_config.items():
            if field in policy_artifact:
                _require_equal(
                    policy_artifact[field],
                    value,
                    f"policy artifact {field} does not match",
                )
        return (
            policy_config,
            _json(root / runtime["evaluation_metrics_path"]),
            _json(root / runtime["evaluation_consumption_path"]),
        )

    def system_summary(self) -> dict:
        summary = {
            "active_runtime_version": self.runtime["version"],
            "model_status": self.model.status,
            "policy_mode": self.policy_mode,
            "feature_contract_version": self.feature_contract_version,
            "feature_contract_sha256": self.feature_contract_sha256,
            "feature_count": self.feature_count,
            "model": self.model.description,
            "model_version": self.runtime["model_version"],
            "model_family": self.model_family,
            "model_candidate": self.model_candidate,
            "calibration": self.calibration,
            "model_stage": self.model_stage,
            "runtime_stage": self.runtime.get("runtime_stage", self.model_stage),
            "policy_stage": self.policy_stage,
            "policy_version": self.policy_version,
            "policy_family": self.policy["family"],
            "evaluation_version": self.runtime["evaluation_version"],
            "evaluation_consumed": self.evaluation_consumed,
            "evaluation_conclusion": self.evaluation_conclusion,
            "evaluation_verdict": self.evaluation_conclusion,
            "production_ready": bool(self.runtime.get("production_ready", False)),
            "environment": {
                "python": sys.version.split()[0],
                "numpy": np.__version__,
                "scikit_learn": sklearn.__version__,
                "platform": platform.system(),
            },
            "synthetic_demonstration": True,
        }
        if self.runtime["version"] == "frozen-v2-runtime":
            summary["blind_evaluated"] = True
            summary["evaluation_status"] = self.evaluation["status"]
        return summary
