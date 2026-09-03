from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from card_testing_sentinel.features.specification_v3 import (
    MODEL_FEATURES_V3,
    MODEL_FEATURES_V3_SHA256,
)
from card_testing_sentinel.ml import pbrss_v1_evaluation as evaluation


def required_freeze(file_path: Path, digest: str) -> dict:
    return {
        "suite_id": evaluation.SUITE_ID,
        "pre_pbrss_model_freeze_commit": evaluation.PRE_PBRSS_COMMIT,
        "feature_contract_sha256": MODEL_FEATURES_V3_SHA256,
        "model_version": "model-v3.1",
        "calibration": "sigmoid",
        "policy_version": "validation-selected-v2",
        "evaluated": False,
        "consumed": False,
        "files": {"fixture": {"path": str(file_path), "sha256": digest}},
    }


def test_evaluator_refuses_missing_freeze(tmp_path: Path) -> None:
    with pytest.raises(evaluation.PBRSSV1EvaluationError, match="missing"):
        evaluation.verify_pre_evaluation(tmp_path)


def test_evaluator_refuses_hash_drift(tmp_path: Path) -> None:
    artifact = tmp_path / "fixture.bin"
    artifact.write_bytes(b"changed")
    freeze = required_freeze(Path("fixture.bin"), "0" * 64)
    path = tmp_path / "artifacts/evaluation/pbrss_v1_freeze_manifest.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(freeze))
    with pytest.raises(evaluation.PBRSSV1EvaluationError, match="hash drift"):
        evaluation.verify_pre_evaluation(tmp_path)


def test_evaluator_refuses_existing_consumption(tmp_path: Path) -> None:
    directory = tmp_path / "artifacts/evaluation"
    directory.mkdir(parents=True)
    (directory / "pbrss_v1_freeze_manifest.json").write_text("{}")
    (directory / "pbrss_v1_consumption.json").write_text("{}")
    with pytest.raises(evaluation.PBRSSV1EvaluationError, match="already"):
        evaluation.verify_pre_evaluation(tmp_path)


def test_evaluator_has_no_training_or_fit_path() -> None:
    source = inspect.getsource(evaluation).lower()
    assert ".fit(" not in source
    assert "train_model" not in source
    assert "training_v3" not in source


def test_evaluator_binds_frozen_stack_and_contract() -> None:
    source = inspect.getsource(evaluation)
    assert evaluation.PRE_PBRSS_COMMIT == "1c9dab4ed2902b4207e6758f1c929fee1b8a08dc"
    assert len(MODEL_FEATURES_V3) == 44
    assert '"model-v3.1"' in source
    assert '"sigmoid"' in source
    assert '"validation-selected-v2"' in source
    assert "RiskPolicyV2" in source


def test_atomic_consumption_reservation_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    freeze_path = tmp_path / "artifacts/evaluation/pbrss_v1_freeze_manifest.json"
    freeze_path.parent.mkdir(parents=True)
    freeze_path.write_text(
        json.dumps(
            {
                "files": {
                    "foundation/model": {"sha256": "m"},
                    "foundation/feature_contract": {"sha256": "f"},
                    "foundation/policy": {"sha256": "p"},
                    "source/evaluation_pipeline": {"sha256": "e"},
                }
            }
        )
    )
    monkeypatch.setattr(evaluation, "git_head", lambda _root: "abc123")
    preflight = {"freeze_sha256": evaluation.sha256_file(freeze_path)}
    evaluation.reserve_consumption(tmp_path, preflight, "start")
    with pytest.raises(evaluation.PBRSSV1EvaluationError, match="already"):
        evaluation.reserve_consumption(tmp_path, preflight, "start")
