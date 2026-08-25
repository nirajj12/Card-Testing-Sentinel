"""Package logging configuration."""

import logging
from logging.handlers import RotatingFileHandler

from card_testing_sentinel.common.config import SentinelSettings

_LOGGER_NAME = "card_testing_sentinel"
_HANDLER_MARKER = "_card_testing_sentinel_handler"
_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


def _remove_configured_handlers(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        if getattr(handler, _HANDLER_MARKER, False):
            logger.removeHandler(handler)
            handler.close()


def _mark_handler(handler: logging.Handler) -> logging.Handler:
    setattr(handler, _HANDLER_MARKER, True)
    return handler


def configure_logging(settings: SentinelSettings) -> logging.Logger:
    """Configure bounded file logging for this package and return its logger."""
    log_directory = settings.paths.logs
    log_directory.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(settings.logging.level)
    logger.propagate = False
    _remove_configured_handlers(logger)

    formatter = logging.Formatter(_FORMAT)
    file_handler = RotatingFileHandler(
        log_directory / settings.logging.filename,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(_mark_handler(file_handler))

    if settings.logging.console_enabled:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(_mark_handler(console_handler))

    return logger
