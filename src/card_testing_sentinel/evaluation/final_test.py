"""Guarded loading and one-time evaluation of the frozen test split."""

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from card_testing_sentinel.common.config import SentinelSettings
from card_testing_sentinel.common.exceptions import PolicyEvaluationError
from card_testing_sentinel.data.loaders import load_device_splits, load_enriched_events
from card_testing_sentinel.data.validation import sha256_file
from card_testing_sentinel.features.spec import MODEL_FEATURES
from card_testing_sentinel.modeling.data import (
    ModelingView,
    frozen_checksums,
    require_phase2_checkpoint,
)


def final_artifact_paths(artifacts_dir: Path, figure_dir: Path) -> tuple[Path, ...]:
    return (
        artifacts_dir / "metrics/final_test_metrics.json",
        artifacts_dir / "predictions/final_test_event_decisions.csv",
        artifacts_dir / "predictions/final_test_device_summary.csv",
        figure_dir / "final_test_detection_by_attempt.png",
        figure_dir / "final_test_policy_comparison.png",
    )


def guard_final_test(
    *,
    confirmed: bool,
    settings: SentinelSettings,
    policy_path: Path,
    training_config_path: Path,
    policy_config_path: Path,
    artifacts_dir: Path,
    figure_dir: Path,
) -> dict[str, Any]:
    """Validate every precondition without loading test rows."""
    if not confirmed:
        raise PolicyEvaluationError(
            "explicit final-evaluation confirmation is required"
        )
    existing = [
        path.name
        for path in final_artifact_paths(artifacts_dir, figure_dir)
        if path.exists()
    ]
    if existing:
        raise PolicyEvaluationError(f"final test artifact already exists: {existing}")
    require_phase2_checkpoint(settings)
    try:
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PolicyEvaluationError("frozen policy is missing or unreadable") from exc
    if (
        policy.get("readiness_status") != "ready_for_final_test"
        or policy.get("test_data_used_for_selection") is not False
    ):
        raise PolicyEvaluationError("validation policy is not ready for final test")
    validation_metrics = artifacts_dir / "metrics/validation_sequential_metrics.json"
    try:
        validation = json.loads(validation_metrics.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PolicyEvaluationError(
            "validation policy selection is incomplete"
        ) from exc
    if validation.get("status") != "passed" or validation.get("champion") != policy.get(
        "selected_policy_method"
    ):
        raise PolicyEvaluationError(
            "validation policy selection does not match frozen policy"
        )
    model_path = settings.paths.artifacts / "models" / policy["model_filename"]
    checks = {
        "model_sha256": sha256_file(model_path),
        "training_config_sha256": sha256_file(training_config_path),
        "policy_config_sha256": sha256_file(policy_config_path),
        "validation_predictions_sha256": sha256_file(
            settings.paths.artifacts / "predictions/validation_predictions.csv"
        ),
    }
    for name, observed in checks.items():
        if policy.get(name) != observed:
            raise PolicyEvaluationError(f"frozen hash mismatch: {name}")
    if policy.get("frozen_checksums") != frozen_checksums(settings):
        raise PolicyEvaluationError("frozen dataset hash mismatch")
    if policy.get("feature_order") != list(MODEL_FEATURES):
        raise PolicyEvaluationError("frozen feature order mismatch")
    return policy


def load_test_view_after_guard(
    settings: SentinelSettings,
) -> tuple[ModelingView, pd.Series]:
    """Construct the test authorization view; call only after guard_final_test."""
    base = settings.paths.frozen_data
    events = load_enriched_events(
        base / settings.frozen_dataset.enriched_events_filename
    )
    splits = load_device_splits(base / settings.frozen_dataset.device_splits_filename)
    test_devices = splits.loc[splits["split"].eq("test"), ["device_id"]]
    selected = events.loc[events["event_type"].eq("authorization")].merge(
        test_devices, on="device_id", how="inner", validate="many_to_one"
    )
    X = selected.loc[:, MODEL_FEATURES].reset_index(drop=True)
    if not np.isfinite(X.to_numpy(dtype=float)).all():
        raise PolicyEvaluationError("test features contain non-finite values")
    metadata_columns = [
        "event_id",
        "event_sequence",
        "timestamp",
        "device_id",
        "session_id",
        "population",
        "attack_subtype",
        "scenario_tag",
    ]
    view = ModelingView(
        X,
        selected["entity_label"].astype(int).rename("label").reset_index(drop=True),
        selected[metadata_columns].reset_index(drop=True),
    )
    return view, selected["card_token"].reset_index(drop=True)
