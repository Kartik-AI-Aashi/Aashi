"""Verify logging configuration."""

from __future__ import annotations

import dataclasses
import logging
from pathlib import Path

from aashi.config import Environment, Settings
from aashi.constants import LOGGER_NAMESPACE
from aashi.logging_setup import configure_logging, get_logger, reset_logging
from aashi.paths import AashiPaths


def make_settings(**overrides: object) -> Settings:
    """Return settings for a logging test, defaulting to file-only output."""
    base = Settings(
        environment=Environment.DEVELOPMENT,
        debug=True,
        log_level="DEBUG",
        log_to_console=False,
        log_to_file=True,
    )
    return dataclasses.replace(base, **overrides)  # type: ignore[arg-type]


def test_configures_the_aashi_namespace_only(isolated_paths: AashiPaths) -> None:
    root_handlers_before = list(logging.getLogger().handlers)

    logger = configure_logging(make_settings(), log_file=isolated_paths.log_file)

    assert logger.name == LOGGER_NAMESPACE
    assert logger.level == logging.DEBUG
    # Aashi owns its namespace end to end and must not touch the root logger.
    assert logger.propagate is False
    assert logging.getLogger().handlers == root_handlers_before


def test_writes_records_to_the_log_file(isolated_paths: AashiPaths) -> None:
    configure_logging(make_settings(), log_file=isolated_paths.log_file)

    get_logger(__name__).info("foundation log line")
    for handler in logging.getLogger(LOGGER_NAMESPACE).handlers:
        handler.flush()

    assert isolated_paths.log_file.is_file()
    assert "foundation log line" in isolated_paths.log_file.read_text(encoding="utf-8")


def test_creates_the_logs_directory_when_missing(isolated_paths: AashiPaths) -> None:
    assert not isolated_paths.logs_dir.exists()

    configure_logging(make_settings(), log_file=isolated_paths.log_file)
    get_logger().info("trigger open")

    assert isolated_paths.logs_dir.is_dir()


def test_repeated_configuration_does_not_accumulate_handlers(
    isolated_paths: AashiPaths,
) -> None:
    first = configure_logging(make_settings(), log_file=isolated_paths.log_file)
    handler_count = len(first.handlers)

    second = configure_logging(make_settings(), log_file=isolated_paths.log_file)

    assert len(second.handlers) == handler_count


def test_console_logging_can_be_enabled(isolated_paths: AashiPaths) -> None:
    logger = configure_logging(
        make_settings(log_to_console=True, log_to_file=False),
        log_file=isolated_paths.log_file,
    )

    assert any(isinstance(handler, logging.StreamHandler) for handler in logger.handlers)
    assert not isolated_paths.log_file.exists()


def test_namespace_always_has_a_handler(isolated_paths: AashiPaths) -> None:
    """With every output disabled, a NullHandler must still absorb records."""
    logger = configure_logging(
        make_settings(log_to_console=False, log_to_file=False),
        log_file=isolated_paths.log_file,
    )

    assert logger.handlers
    assert isinstance(logger.handlers[0], logging.NullHandler)


def test_unopenable_log_file_does_not_prevent_startup(tmp_path: Path) -> None:
    """A log path blocked by a file must degrade to a warning, not an exception."""
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")

    logger = configure_logging(make_settings(), log_file=blocker / "logs" / "aashi.log")

    assert logger.handlers  # Startup survived.


def test_get_logger_namespaces_module_names() -> None:
    assert get_logger().name == LOGGER_NAMESPACE
    assert get_logger("aashi.paths").name == "aashi.paths"
    assert get_logger("custom").name == f"{LOGGER_NAMESPACE}.custom"


def test_reset_logging_detaches_handlers(isolated_paths: AashiPaths) -> None:
    configure_logging(make_settings(), log_file=isolated_paths.log_file)

    reset_logging()

    assert logging.getLogger(LOGGER_NAMESPACE).handlers == []
