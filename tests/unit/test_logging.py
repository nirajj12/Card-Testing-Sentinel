import logging
from pathlib import Path

import pytest

from card_testing_sentinel.common.config import (
    LoggingSettings,
    PathSettings,
    SentinelSettings,
)
from card_testing_sentinel.common.logging import configure_logging


def _settings(tmp_path: Path, *, console_enabled: bool = False) -> SentinelSettings:
    return SentinelSettings(
        project_name="Test Sentinel",
        random_seed=17,
        paths=PathSettings(
            frozen_data=tmp_path / "data" / "frozen",
            runtime_data=tmp_path / "data" / "runtime",
            artifacts=tmp_path / "artifacts",
            logs=tmp_path / "nested" / "logs",
            reports=tmp_path / "reports",
            mlflow=tmp_path / "mlruns",
        ),
        logging=LoggingSettings(
            level="INFO",
            filename="test.log",
            console_enabled=console_enabled,
        ),
    )


@pytest.fixture(autouse=True)
def clean_package_logger() -> None:
    logger = logging.getLogger("card_testing_sentinel")
    yield
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


def test_configure_logging_creates_directory_and_writes_file(tmp_path: Path) -> None:
    settings = _settings(tmp_path)

    logger = configure_logging(settings)
    logger.info("known file message")
    for handler in logger.handlers:
        handler.flush()

    log_file = settings.paths.logs / settings.logging.filename
    assert log_file.is_file()
    assert "known file message" in log_file.read_text(encoding="utf-8")


def test_configure_logging_respects_console_setting(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    logger = configure_logging(_settings(tmp_path, console_enabled=True))
    logger.info("visible console message")
    assert "visible console message" in capsys.readouterr().err

    logger = configure_logging(_settings(tmp_path, console_enabled=False))
    logger.info("file only message")
    assert "file only message" not in capsys.readouterr().err


def test_reconfiguration_does_not_duplicate_output(tmp_path: Path) -> None:
    settings = _settings(tmp_path)

    logger = configure_logging(settings)
    logger = configure_logging(settings)
    logger.info("single occurrence")
    for handler in logger.handlers:
        handler.flush()

    contents = (settings.paths.logs / settings.logging.filename).read_text(
        encoding="utf-8"
    )
    assert contents.count("single occurrence") == 1
