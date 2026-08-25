"""Leakage-safe authorization-only modeling views."""

import json
from dataclasses import dataclass

import numpy as np
import pandas as pd

from card_testing_sentinel.common.config import SentinelSettings
from card_testing_sentinel.common.exceptions import ModelTrainingError
from card_testing_sentinel.data.loaders import load_device_splits, load_enriched_events
from card_testing_sentinel.data.validation import sha256_file
from card_testing_sentinel.features.spec import MODEL_FEATURES

METADATA_COLUMNS = (
    "event_id",
    "event_sequence",
    "timestamp",
    "device_id",
    "session_id",
    "population",
    "attack_subtype",
    "scenario_tag",
)


@dataclass(frozen=True)
class ModelingView:
    """Features, labels, and evaluation metadata kept physically separate."""

    X: pd.DataFrame
    y: pd.Series
    metadata: pd.DataFrame


def frozen_checksums(settings: SentinelSettings) -> dict[str, str]:
    """Return current checksums for the three immutable CSV files."""
    base = settings.paths.frozen_data
    frozen = settings.frozen_dataset
    return {
        frozen.raw_events_filename: sha256_file(base / frozen.raw_events_filename),
        frozen.enriched_events_filename: sha256_file(
            base / frozen.enriched_events_filename
        ),
        frozen.device_splits_filename: sha256_file(
            base / frozen.device_splits_filename
        ),
    }


def require_phase2_checkpoint(settings: SentinelSettings) -> dict[str, str]:
    """Require a passed report and manifest-matching current CSV checksums."""
    report_path = settings.frozen_dataset.report_path
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ModelTrainingError(
            "Phase 2 validation report is missing or unreadable"
        ) from exc
    status = report.get("overall_status", report.get("status"))
    if status not in {"pass", "passed"} or report.get("total_checks_failed", 1) != 0:
        raise ModelTrainingError("Phase 2 validation report is not passed")

    manifest_path = (
        settings.paths.frozen_data / settings.frozen_dataset.manifest_filename
    )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ModelTrainingError("Frozen manifest is missing or unreadable") from exc
    current = frozen_checksums(settings)
    expected = {name: entry["sha256"] for name, entry in manifest["files"].items()}
    if current != expected:
        raise ModelTrainingError("Frozen CSV checksums do not match the v4 manifest")
    return current


def _build_view(
    events: pd.DataFrame, assignments: pd.DataFrame, split: str
) -> ModelingView:
    selected_devices = assignments.loc[
        assignments["split"].eq(split), ["device_id", "split"]
    ]
    authorization = events.loc[events["event_type"].eq("authorization")]
    selected = authorization.merge(
        selected_devices, on="device_id", how="inner", validate="many_to_one"
    )
    if selected.empty or not selected["split"].eq(split).all():
        raise ModelTrainingError(f"invalid or empty {split} modeling view")
    X = selected.loc[:, MODEL_FEATURES].copy()
    values = X.to_numpy(dtype=float)
    if tuple(X.columns) != MODEL_FEATURES or not np.isfinite(values).all():
        raise ModelTrainingError(
            f"{split} features are missing, reordered, or non-finite"
        )
    y = selected["entity_label"].astype(int).rename("label")
    metadata = selected.loc[:, METADATA_COLUMNS].copy()
    if selected.groupby("device_id")["entity_label"].nunique().max() != 1:
        raise ModelTrainingError("device labels are not stable")
    return ModelingView(
        X.reset_index(drop=True),
        y.reset_index(drop=True),
        metadata.reset_index(drop=True),
    )


def load_training_view(settings: SentinelSettings) -> ModelingView:
    """Load only the training authorization view for EDA."""
    require_phase2_checkpoint(settings)
    base = settings.paths.frozen_data
    events = load_enriched_events(
        base / settings.frozen_dataset.enriched_events_filename
    )
    splits = load_device_splits(base / settings.frozen_dataset.device_splits_filename)
    return _build_view(events, splits, "train")


def load_train_validation_views(
    settings: SentinelSettings,
) -> tuple[ModelingView, ModelingView]:
    """Return train and validation views; never construct a test view."""
    require_phase2_checkpoint(settings)
    base = settings.paths.frozen_data
    events = load_enriched_events(
        base / settings.frozen_dataset.enriched_events_filename
    )
    splits = load_device_splits(base / settings.frozen_dataset.device_splits_filename)
    train = _build_view(events, splits, "train")
    validation = _build_view(events, splits, "validation")
    if set(train.metadata["device_id"]) & set(validation.metadata["device_id"]):
        raise ModelTrainingError("train and validation devices overlap")
    test_devices = set(splits.loc[splits["split"].eq("test"), "device_id"])
    if test_devices & (
        set(train.metadata["device_id"]) | set(validation.metadata["device_id"])
    ):
        raise ModelTrainingError("test device leaked into Phase 3 views")
    return train, validation
