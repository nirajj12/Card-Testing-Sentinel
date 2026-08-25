import json
from pathlib import Path

import yaml

from card_testing_sentinel.common.config import load_config
from card_testing_sentinel.evaluation.eda import run_training_eda
from card_testing_sentinel.modeling.data import (
    frozen_checksums,
    load_train_validation_views,
)
from card_testing_sentinel.modeling.training import require_current_eda, run_training

ROOT = Path(__file__).resolve().parents[2]


def test_real_frozen_data_runs_eda_then_tiny_baseline_pipeline(tmp_path):
    settings = load_config(ROOT / "configs/base.yaml")
    config = yaml.safe_load((ROOT / "configs/training.yaml").read_text())
    config["logistic_candidates"] = [config["logistic_candidates"][0]]
    hgb = dict(config["hist_gradient_boosting_candidates"][0])
    hgb["max_iter"] = 20
    config["hist_gradient_boosting_candidates"] = [hgb]
    train, validation = load_train_validation_views(settings)
    checksums = frozen_checksums(settings)
    artifacts = tmp_path / "artifacts"
    figures = tmp_path / "figures"
    summary = run_training_eda(
        train,
        checksums=checksums,
        dataset_version="v4",
        metrics_dir=artifacts / "metrics",
        figure_dir=figures,
        shortcut_limit=1.0,
    )
    assert summary["validation_rows"] == summary["test_rows"] == 0
    result = run_training(
        train,
        validation,
        config=config,
        seed=42,
        checksums=checksums,
        dataset_version="v4",
        eda_path=artifacts / "metrics/training_eda_summary.json",
        artifacts_dir=artifacts,
        figure_dir=figures,
        mlflow_dir=tmp_path / "mlruns",
    )
    assert result["champion"] in {"logistic_regression", "hist_gradient_boosting"}
    assert (artifacts / "predictions/validation_predictions.csv").exists()
    assert not (artifacts / "predictions/test_predictions.csv").exists()
    assert all(
        item["device_overlap"].eq(0).all()
        for _, item in result["cross_validation"].groupby("candidate")
    )
    assert frozen_checksums(settings) == checksums
    payload = json.loads((artifacts / "metrics/training_eda_summary.json").read_text())
    payload["frozen_checksums"] = {"stale": "yes"}
    stale = tmp_path / "stale.json"
    stale.write_text(json.dumps(payload))
    try:
        require_current_eda(stale, checksums)
    except Exception as exc:
        assert "stale" in str(exc)
    else:
        raise AssertionError("stale EDA summary was accepted")
