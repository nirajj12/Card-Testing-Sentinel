from pathlib import Path

import pytest

from card_testing_sentinel.common.config import load_config
from card_testing_sentinel.common.exceptions import ConfigurationError


def _write_config(config_path: Path, *, level: str = "INFO") -> None:
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        f"""
project_name: Test Sentinel
random_seed: 17
paths:
  frozen_data: data/frozen
  runtime_data: data/runtime
  artifacts: artifacts
  logs: logs
  reports: reports
  mlflow: mlruns
logging:
  level: {level}
  filename: test.log
  console_enabled: false
""".strip(),
        encoding="utf-8",
    )


def test_load_config_accepts_valid_yaml(tmp_path: Path) -> None:
    config_path = tmp_path / "configs" / "base.yaml"
    _write_config(config_path)

    settings = load_config(config_path)

    assert settings.project_name == "Test Sentinel"
    assert settings.random_seed == 17
    assert settings.logging.level == "INFO"


def test_load_config_resolves_paths_from_project_root(tmp_path: Path) -> None:
    config_path = tmp_path / "configs" / "base.yaml"
    _write_config(config_path)

    settings = load_config(config_path)

    assert settings.paths.frozen_data == tmp_path / "data" / "frozen"
    assert settings.paths.logs == tmp_path / "logs"
    assert settings.paths.mlflow == tmp_path / "mlruns"


def test_load_config_rejects_missing_file(tmp_path: Path) -> None:
    missing_path = tmp_path / "configs" / "missing.yaml"

    with pytest.raises(ConfigurationError, match="does not exist"):
        load_config(missing_path)


def test_load_config_translates_malformed_yaml(tmp_path: Path) -> None:
    config_path = tmp_path / "configs" / "base.yaml"
    config_path.parent.mkdir()
    config_path.write_text("logging: [broken", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="could not read") as error:
        load_config(config_path)

    assert error.value.__cause__ is not None


def test_load_config_translates_invalid_settings(tmp_path: Path) -> None:
    config_path = tmp_path / "configs" / "base.yaml"
    _write_config(config_path, level="VERBOSE")

    with pytest.raises(ConfigurationError, match="invalid configuration") as error:
        load_config(config_path)

    assert error.value.__cause__ is not None
