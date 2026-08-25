"""Typed application configuration loaded from an explicit YAML file."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from card_testing_sentinel.common.exceptions import ConfigurationError


class PathSettings(BaseModel):
    """Project paths used by application and experiment code."""

    model_config = ConfigDict(frozen=True)

    frozen_data: Path
    runtime_data: Path
    artifacts: Path
    logs: Path
    reports: Path
    mlflow: Path


class LoggingSettings(BaseModel):
    """Standard-library logging options."""

    model_config = ConfigDict(frozen=True)

    level: str = "INFO"
    filename: str = "sentinel.log"
    console_enabled: bool = True

    @field_validator("level")
    @classmethod
    def validate_level(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"unsupported logging level: {value}")
        return normalized

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str) -> str:
        if not value.strip() or Path(value).name != value:
            raise ValueError("logging filename must be a plain filename")
        return value


class FrozenDatasetSettings(BaseModel):
    """Names and locations for the immutable v4 dataset contract."""

    model_config = ConfigDict(frozen=True)

    version: str = "v4"
    archive_path: Path = Path("razorpay (1).zip")
    manifest_filename: str = "manifest.json"
    raw_events_filename: str = "raw_events.csv"
    enriched_events_filename: str = "events_with_features.csv"
    device_splits_filename: str = "device_splits.csv"
    report_path: Path = Path("reports/data_validation_report.json")


class SentinelSettings(BaseModel):
    """Validated settings for the current project foundation."""

    model_config = ConfigDict(frozen=True)

    project_name: str = Field(min_length=1)
    random_seed: int = Field(ge=0)
    paths: PathSettings
    logging: LoggingSettings
    frozen_dataset: FrozenDatasetSettings = Field(default_factory=FrozenDatasetSettings)


def _resolve_paths(paths: PathSettings, project_root: Path) -> PathSettings:
    resolved: dict[str, Path] = {}
    for name, value in paths:
        resolved[name] = (
            value if value.is_absolute() else (project_root / value).resolve()
        )
    return PathSettings.model_validate(resolved)


def _resolve_frozen_dataset(
    frozen_dataset: FrozenDatasetSettings, project_root: Path
) -> FrozenDatasetSettings:
    updates = {}
    for field_name in ("archive_path", "report_path"):
        value = getattr(frozen_dataset, field_name)
        updates[field_name] = (
            value if value.is_absolute() else (project_root / value).resolve()
        )
    return frozen_dataset.model_copy(update=updates)


def load_config(config_path: str | Path) -> SentinelSettings:
    """Load settings and resolve relative paths from the project root.

    The project root is the parent of the directory containing the YAML file,
    matching the repository's ``configs/base.yaml`` layout.
    """
    path = Path(config_path).expanduser()
    if not path.exists():
        raise ConfigurationError(f"configuration file does not exist: {path}")
    if not path.is_file():
        raise ConfigurationError(f"configuration path is not a file: {path}")

    try:
        raw_config: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"could not read configuration file: {path}") from exc

    try:
        settings = SentinelSettings.model_validate(raw_config)
    except ValidationError as exc:
        raise ConfigurationError(f"invalid configuration in {path}: {exc}") from exc

    project_root = path.resolve().parent.parent
    return settings.model_copy(
        update={
            "paths": _resolve_paths(settings.paths, project_root),
            "frozen_dataset": _resolve_frozen_dataset(
                settings.frozen_dataset, project_root
            ),
        }
    )
