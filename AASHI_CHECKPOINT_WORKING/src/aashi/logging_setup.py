"""Logging configuration for Aashi.

Aashi configures only its own logger namespace (``aashi``) and never the root
logger, so that embedding Aashi code in another process — or in pytest — does
not hijack unrelated logging.

Configuration is idempotent: calling :func:`configure_logging` twice replaces
the handlers rather than accumulating duplicates.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from aashi.config import Settings
from aashi.constants import (
    LOG_DATE_FORMAT,
    LOG_FILE_BACKUP_COUNT,
    LOG_FILE_MAX_BYTES,
    LOG_FORMAT,
    LOGGER_NAMESPACE,
)

__all__ = ["configure_logging", "get_logger", "reset_logging"]


def get_logger(name: str | None = None) -> logging.Logger:
    """Return an Aashi logger.

    Args:
        name: Dotted name relative to the Aashi namespace, or a full module
            name (``__name__``). Omit for the namespace root logger.
    """
    if not name:
        return logging.getLogger(LOGGER_NAMESPACE)
    if name == LOGGER_NAMESPACE or name.startswith(f"{LOGGER_NAMESPACE}."):
        return logging.getLogger(name)
    return logging.getLogger(f"{LOGGER_NAMESPACE}.{name}")


def reset_logging() -> None:
    """Remove and close every handler attached to the Aashi logger namespace.

    Closing handlers matters on Windows, where an open log file cannot be moved
    or deleted. Tests rely on this to release temporary directories.
    """
    logger = logging.getLogger(LOGGER_NAMESPACE)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


def configure_logging(settings: Settings, log_file: Path | None = None) -> logging.Logger:
    """Configure the Aashi logger namespace from ``settings``.

    Args:
        settings: Resolved application settings.
        log_file: Destination for the rotating file handler. Required when
            :attr:`Settings.log_to_file` is enabled; typically
            :attr:`aashi.paths.AashiPaths.log_file`.

    Returns:
        The configured namespace logger.

    Notes:
        If the log file cannot be opened — read-only install directory, locked
        file, missing permissions — file logging is skipped and a warning is
        emitted. Failure to write logs must never prevent Aashi from starting.
    """
    logger = logging.getLogger(LOGGER_NAMESPACE)
    reset_logging()

    logger.setLevel(settings.numeric_log_level)
    # Aashi owns this namespace end to end; don't leak records to the root logger.
    logger.propagate = False

    formatter = logging.Formatter(fmt=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)

    if settings.log_to_console:
        console_handler = logging.StreamHandler(stream=sys.stderr)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    file_error: OSError | None = None
    if settings.log_to_file and log_file is not None:
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                filename=log_file,
                maxBytes=LOG_FILE_MAX_BYTES,
                backupCount=LOG_FILE_BACKUP_COUNT,
                encoding="utf-8",
                delay=True,
            )
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except OSError as exc:
            file_error = exc

    if not logger.handlers:
        # Never leave the namespace unhandled; that produces "no handlers"
        # warnings and silently discards diagnostics.
        logger.addHandler(logging.NullHandler())

    if file_error is not None:
        logger.warning("File logging disabled; could not open %s (%s).", log_file, file_error)

    return logger
