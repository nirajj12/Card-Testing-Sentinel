import json
from pathlib import Path

import pytest

from card_testing_sentinel.common.config import load_config
from card_testing_sentinel.common.exceptions import PolicyEvaluationError
from card_testing_sentinel.evaluation.final_test import guard_final_test
from card_testing_sentinel.modeling.data import frozen_checksums

ROOT = Path(__file__).resolve().parents[2]


def test_guard_refuses_without_confirmation(tmp_path):
    settings = load_config(ROOT / "configs/base.yaml")
    with pytest.raises(PolicyEvaluationError, match="confirmation"):
        guard_final_test(
            confirmed=False,
            settings=settings,
            policy_path=tmp_path / "none",
            training_config_path=ROOT / "configs/training.yaml",
            policy_config_path=ROOT / "configs/policy.yaml",
            artifacts_dir=tmp_path,
            figure_dir=tmp_path,
        )


def test_guard_refuses_existing_artifact_before_loading_test(tmp_path):
    settings = load_config(ROOT / "configs/base.yaml")
    metrics = tmp_path / "metrics"
    metrics.mkdir()
    (metrics / "final_test_metrics.json").write_text("{}")
    with pytest.raises(PolicyEvaluationError, match="already exists"):
        guard_final_test(
            confirmed=True,
            settings=settings,
            policy_path=tmp_path / "none",
            training_config_path=ROOT / "configs/training.yaml",
            policy_config_path=ROOT / "configs/policy.yaml",
            artifacts_dir=tmp_path,
            figure_dir=tmp_path,
        )


def test_guard_refuses_hash_mismatch(tmp_path):
    settings = load_config(ROOT / "configs/base.yaml")
    metrics = tmp_path / "metrics"
    metrics.mkdir()
    (metrics / "validation_sequential_metrics.json").write_text(
        json.dumps({"status": "passed", "champion": "rules_only"})
    )
    policy = {
        "readiness_status": "ready_for_final_test",
        "test_data_used_for_selection": False,
        "selected_policy_method": "rules_only",
        "model_filename": "hist_gradient_boosting.joblib",
        "model_sha256": "wrong",
        "frozen_checksums": frozen_checksums(settings),
        "feature_order": [],
    }
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(policy))
    with pytest.raises(PolicyEvaluationError, match="hash mismatch"):
        guard_final_test(
            confirmed=True,
            settings=settings,
            policy_path=policy_path,
            training_config_path=ROOT / "configs/training.yaml",
            policy_config_path=ROOT / "configs/policy.yaml",
            artifacts_dir=tmp_path,
            figure_dir=tmp_path,
        )
