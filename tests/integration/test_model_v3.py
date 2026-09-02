"""Integration test for Model v3 artifact loading, inference, and contract verification."""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest

from card_testing_sentinel.features.specification_v3 import (
    FEATURE_CONTRACT_V3_VERSION,
    MODEL_FEATURES_V3,
    MODEL_FEATURES_V3_SHA256,
)
from card_testing_sentinel.ml.training_v3 import RiskModelArtifactV3

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS_DIR = ROOT / "artifacts/model_v3_1"


def test_model_v3_artifacts_and_contract() -> None:
    assert (ARTIFACTS_DIR / "risk_model_v3_1.joblib").exists()
    assert (ARTIFACTS_DIR / "metadata.json").exists()
    assert (ARTIFACTS_DIR / "feature_contract.json").exists()

    contract = json.loads((ARTIFACTS_DIR / "feature_contract.json").read_text())
    assert contract["version"] == FEATURE_CONTRACT_V3_VERSION
    assert contract["sha256"] == MODEL_FEATURES_V3_SHA256
    assert len(contract["features"]) == 44


def test_model_v3_inference_pipeline() -> None:
    model_artifact = joblib.load(ARTIFACTS_DIR / "risk_model_v3_1.joblib")
    assert isinstance(model_artifact, RiskModelArtifactV3)
    assert model_artifact.feature_contract_sha256 == MODEL_FEATURES_V3_SHA256

    sample_dict = {f: 0.0 for f in MODEL_FEATURES_V3}
    sample_df = pd.DataFrame([sample_dict])

    scores = model_artifact.score_frame(sample_df)
    assert len(scores) == 1
    assert 0.0 <= scores[0] <= 1.0
