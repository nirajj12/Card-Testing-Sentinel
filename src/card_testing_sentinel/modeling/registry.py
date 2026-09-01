"""Startup-loaded runtime configuration and model handle.

Loads the feature contract (from code), the policy config, and the frozen
development model. The model is a *development-frozen candidate*: it has been
selected on train cross-validation and measured on validation, but it has not
faced a blind set, so the runtime says so rather than implying final numbers.
"""

from __future__ import annotations

import platform
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import sklearn

from card_testing_sentinel.common.config import load_config
from card_testing_sentinel.features.specification import (
    FEATURE_CONTRACT_VERSION,
    MODEL_FEATURES,
    MODEL_FEATURES_SHA256,
    validate_feature_contract,
)
from card_testing_sentinel.modeling.model import RiskModel


@dataclass
class ArtifactRegistry:
    root: Path
    model: RiskModel
    policy: dict
    policy_mode: str
    feature_contract_version: str
    feature_contract_sha256: str
    feature_count: int
    model_stage: str
    policy_stage: str
    policy_version: str

    @classmethod
    def load(cls, root: Path) -> ArtifactRegistry:
        validate_feature_contract()
        policy_config = load_config(root / "configs/policy.yaml")["policy"]
        model = RiskModel.load(root)
        return cls(
            root=root,
            model=model,
            policy=policy_config,
            policy_mode="model_and_rules" if model.available else "degraded_rules_only",
            feature_contract_version=FEATURE_CONTRACT_VERSION,
            feature_contract_sha256=MODEL_FEATURES_SHA256,
            feature_count=len(MODEL_FEATURES),
            model_stage=(
                "development_frozen_candidate" if model.available else "unavailable"
            ),
            policy_stage="validation_selected",
            policy_version=str(policy_config["version"]),
        )

    def system_summary(self) -> dict:
        return {
            "model_status": self.model.status,
            "policy_mode": self.policy_mode,
            "feature_contract_version": self.feature_contract_version,
            "feature_contract_sha256": self.feature_contract_sha256,
            "feature_count": self.feature_count,
            "model": self.model.description,
            "model_stage": self.model_stage,
            "policy_stage": self.policy_stage,
            "policy_version": self.policy_version,
            "policy_family": self.policy["family"],
            "blind_evaluated": False,
            "evaluation_status": "development_validation_only",
            "evaluation_reason": (
                "The model was selected on train cross-validation and measured "
                "on the validation split. No blind evaluation has been run, so "
                "no held-out performance is claimed."
            ),
            "environment": {
                "python": sys.version.split()[0],
                "numpy": np.__version__,
                "scikit_learn": sklearn.__version__,
                "platform": platform.system(),
            },
            "synthetic_demonstration": True,
        }
