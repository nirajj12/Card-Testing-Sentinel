"""Typed, read-only loaders for the frozen v4 CSV bundle."""

import csv
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from card_testing_sentinel.common.config import SentinelSettings
from card_testing_sentinel.common.exceptions import DataValidationError
from card_testing_sentinel.data.contracts import (
    DEVICE_SPLIT_COLUMNS,
    ENRICHED_EVENT_COLUMNS,
    RAW_EVENT_COLUMNS,
)
from card_testing_sentinel.features.spec import MODEL_FEATURES

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FrozenBundle:
    """The three in-memory tables required for complete validation."""

    raw_events: pd.DataFrame
    enriched_events: pd.DataFrame
    device_splits: pd.DataFrame
    manifest: dict[str, Any]


def _require_regular_file(path: Path) -> None:
    if not path.exists():
        raise DataValidationError(f"frozen data file does not exist: {path.name}")
    if not path.is_file():
        raise DataValidationError(f"frozen data path is not a file: {path.name}")


def _require_header(path: Path, expected: tuple[str, ...]) -> None:
    _require_regular_file(path)
    try:
        with path.open(newline="", encoding="utf-8") as stream:
            actual = tuple(next(csv.reader(stream)))
    except (OSError, StopIteration, UnicodeError, csv.Error) as exc:
        raise DataValidationError(f"could not read CSV header: {path.name}") from exc
    if actual != expected:
        missing = [column for column in expected if column not in actual]
        unexpected = [column for column in actual if column not in expected]
        raise DataValidationError(
            f"invalid columns for {path.name}; missing={missing}, "
            f"unexpected={unexpected}, order_matches={actual == expected}"
        )


def _read_strings(path: Path, columns: tuple[str, ...]) -> pd.DataFrame:
    _require_header(path, columns)
    try:
        return pd.read_csv(path, dtype="string", keep_default_na=True)
    except (OSError, UnicodeError, ValueError, pd.errors.ParserError) as exc:
        raise DataValidationError(f"could not parse frozen CSV: {path.name}") from exc


def _to_numeric(frame: pd.DataFrame, columns: tuple[str, ...], filename: str) -> None:
    for column in columns:
        try:
            frame[column] = pd.to_numeric(frame[column], errors="raise")
        except (TypeError, ValueError) as exc:
            raise DataValidationError(
                f"column {column!r} in {filename} contains invalid numeric data"
            ) from exc


def _normalize_declined(frame: pd.DataFrame, filename: str) -> None:
    normalized = frame["declined"].str.strip().str.lower()
    invalid = normalized.notna() & ~normalized.isin(["true", "false"])
    if invalid.any():
        raise DataValidationError(
            f"column 'declined' in {filename} is not nullable boolean"
        )
    frame["declined"] = normalized.map({"true": True, "false": False}).astype("boolean")


def _normalize_events(frame: pd.DataFrame, filename: str, *, enriched: bool) -> None:
    try:
        frame["timestamp"] = pd.to_datetime(
            frame["timestamp"], format="ISO8601", errors="raise"
        )
    except (TypeError, ValueError) as exc:
        raise DataValidationError(
            f"column 'timestamp' in {filename} is invalid"
        ) from exc

    numeric_columns = ("event_sequence", "amount", "entity_label")
    if enriched:
        numeric_columns += MODEL_FEATURES
    _to_numeric(frame, numeric_columns, filename)
    _normalize_declined(frame, filename)
    frame["card_bin"] = frame["card_bin"].str.replace(r"\.0$", "", regex=True)


def load_raw_events(path: Path) -> pd.DataFrame:
    """Load raw events with identifiers and nullable outcomes preserved."""
    frame = _read_strings(path, RAW_EVENT_COLUMNS)
    _normalize_events(frame, path.name, enriched=False)
    logger.info("Loaded frozen file %s with %d rows", path.name, len(frame))
    return frame


def load_enriched_events(path: Path) -> pd.DataFrame:
    """Load enriched events and require every allowlisted feature to be numeric."""
    frame = _read_strings(path, ENRICHED_EVENT_COLUMNS)
    _normalize_events(frame, path.name, enriched=True)
    logger.info("Loaded frozen file %s with %d rows", path.name, len(frame))
    return frame


def load_device_splits(path: Path) -> pd.DataFrame:
    """Load frozen one-row-per-device split assignments as strings."""
    frame = _read_strings(path, DEVICE_SPLIT_COLUMNS)
    logger.info("Loaded frozen file %s with %d rows", path.name, len(frame))
    return frame


def load_manifest(path: Path) -> dict[str, Any]:
    """Load the deterministic frozen-data manifest."""
    _require_regular_file(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DataValidationError(
            f"could not load frozen manifest: {path.name}"
        ) from exc
    if not isinstance(data, dict):
        raise DataValidationError("frozen manifest must contain a JSON object")
    return data


def load_frozen_bundle(settings: SentinelSettings) -> FrozenBundle:
    """Load the complete frozen bundle from validated application settings."""
    directory = settings.paths.frozen_data
    frozen = settings.frozen_dataset
    return FrozenBundle(
        raw_events=load_raw_events(directory / frozen.raw_events_filename),
        enriched_events=load_enriched_events(
            directory / frozen.enriched_events_filename
        ),
        device_splits=load_device_splits(directory / frozen.device_splits_filename),
        manifest=load_manifest(directory / frozen.manifest_filename),
    )
