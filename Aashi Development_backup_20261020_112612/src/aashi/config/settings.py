"""Lightweight configuration foundation for Aashi.

This is deliberately *not* the Aashi settings system. It provides the minimum
needed to start the application in a known state: which environment we are in,
whether debug behaviour is enabled, and how logging behaves.

Configuration is layered, lowest precedence first:

1. Built-in defaults defined in this module.
2. The bundled TOML file for the active environment (``config/<env>.toml``).
3. Environment variable overrides.

Only tables this module knows about are read. Unknown *tables* are ignored so
that future modules can add their own sections without touching this file;
unknown *keys inside a known table* raise :class:`ConfigError`, because those
are almost always typos.

No secrets are read, stored or expected here. Credentials belong to Aashi's
future secure credential system.
"""

from __future__ import annotations

import logging
import os
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Final

from aashi.config.environment import Environment, detect_environment
from aashi.constants import CONFIG_FILE_SUFFIX, ENV_VAR_DEBUG, ENV_VAR_LOG_LEVEL

__all__ = ["ConfigError", "Settings", "load_settings"]

_logger = logging.getLogger(__name__)

_VALID_LOG_LEVELS: Final[frozenset[str]] = frozenset(
    {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
)

_TRUE_VALUES: Final[frozenset[str]] = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES: Final[frozenset[str]] = frozenset({"0", "false", "no", "off"})


class ConfigError(Exception):
    """Raised when configuration is present but invalid.

    A *missing* configuration file is not an error — defaults apply. Malformed
    TOML, unknown keys and out-of-range values are errors, and must fail loudly
    at startup rather than silently changing behaviour.
    """


@dataclass(frozen=True, slots=True)
class Settings:
    """Immutable application settings for one run.

    Attributes:
        environment: The active environment.
        debug: Enables development-oriented behaviour. Never enabled by
            default in production.
        log_level: Level name applied to the Aashi logger namespace.
        log_to_console: Whether log records are written to stderr.
        log_to_file: Whether log records are written to the rotating log file.
    """

    environment: Environment = Environment.DEVELOPMENT
    debug: bool = False
    log_level: str = "INFO"
    log_to_console: bool = True
    log_to_file: bool = True

    @property
    def numeric_log_level(self) -> int:
        """The :mod:`logging` integer level corresponding to :attr:`log_level`."""
        return logging.getLevelNamesMapping()[self.log_level]


# Per-environment defaults, applied before any file or environment override.
_ENVIRONMENT_DEFAULTS: Final[dict[Environment, dict[str, Any]]] = {
    Environment.DEVELOPMENT: {"debug": True, "log_level": "DEBUG", "log_to_console": True},
    Environment.PRODUCTION: {"debug": False, "log_level": "INFO", "log_to_console": False},
}

# Mapping of "<table>.<key>" in TOML to Settings field names.
_FILE_KEY_MAP: Final[dict[tuple[str, str], str]] = {
    ("app", "debug"): "debug",
    ("logging", "level"): "log_level",
    ("logging", "console"): "log_to_console",
    ("logging", "file"): "log_to_file",
}

_KNOWN_TABLES: Final[frozenset[str]] = frozenset(table for table, _ in _FILE_KEY_MAP)


def _coerce_bool(value: object, source: str) -> bool:
    """Coerce a TOML or environment value to ``bool``, or raise ConfigError."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in _TRUE_VALUES:
            return True
        if lowered in _FALSE_VALUES:
            return False
    raise ConfigError(f"{source}: expected a boolean, got {value!r}")


def _coerce_log_level(value: object, source: str) -> str:
    """Validate and normalize a log level name, or raise ConfigError."""
    if not isinstance(value, str):
        raise ConfigError(f"{source}: expected a log level name, got {value!r}")
    level = value.strip().upper()
    if level not in _VALID_LOG_LEVELS:
        valid = ", ".join(sorted(_VALID_LOG_LEVELS))
        raise ConfigError(f"{source}: unknown log level {value!r}. Expected one of: {valid}")
    return level


def _read_config_file(path: Path) -> dict[str, Any]:
    """Parse a TOML configuration file into overrides for :class:`Settings`.

    Returns an empty mapping when the file does not exist.
    """
    if not path.is_file():
        _logger.debug("No configuration file at %s; using defaults.", path)
        return {}

    try:
        with path.open("rb") as handle:
            document = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: invalid TOML ({exc})") from exc
    except OSError as exc:
        raise ConfigError(f"{path}: could not be read ({exc})") from exc

    overrides: dict[str, Any] = {}
    for table_name, table in document.items():
        if table_name not in _KNOWN_TABLES:
            # Reserved for future modules; not this module's business.
            _logger.debug("%s: ignoring unrecognized table [%s].", path, table_name)
            continue
        if not isinstance(table, dict):
            raise ConfigError(f"{path}: [{table_name}] must be a table")
        for key, value in table.items():
            field = _FILE_KEY_MAP.get((table_name, key))
            if field is None:
                raise ConfigError(f"{path}: unknown key '{key}' in [{table_name}]")
            source = f"{path} [{table_name}].{key}"
            if field == "log_level":
                overrides[field] = _coerce_log_level(value, source)
            else:
                overrides[field] = _coerce_bool(value, source)
    return overrides


def _read_env_overrides(environ: dict[str, str]) -> dict[str, Any]:
    """Collect settings overrides from environment variables."""
    overrides: dict[str, Any] = {}
    if (raw_level := environ.get(ENV_VAR_LOG_LEVEL)) is not None:
        overrides["log_level"] = _coerce_log_level(raw_level, ENV_VAR_LOG_LEVEL)
    if (raw_debug := environ.get(ENV_VAR_DEBUG)) is not None:
        overrides["debug"] = _coerce_bool(raw_debug, ENV_VAR_DEBUG)
    return overrides


def load_settings(
    *,
    environment: Environment | None = None,
    config_dir: Path | None = None,
    env: dict[str, str] | None = None,
) -> Settings:
    """Load settings for the current run.

    Args:
        environment: Environment to load. Defaults to
            :func:`~aashi.config.environment.detect_environment`.
        config_dir: Directory holding ``<environment>.toml``. When omitted, no
            file is read and defaults plus environment overrides apply. Callers
            that want the bundled files pass
            :attr:`~aashi.paths.AashiPaths.bundled_config_dir`.
        env: Environment mapping to read from. Defaults to ``os.environ``.

    Returns:
        An immutable :class:`Settings` instance.

    Raises:
        ConfigError: If configuration exists but is invalid.
    """
    environ = os.environ if env is None else env
    resolved_environment = environment or detect_environment(env=environ)

    settings = replace(
        Settings(environment=resolved_environment),
        **_ENVIRONMENT_DEFAULTS[resolved_environment],
    )

    if config_dir is not None:
        config_path = config_dir / f"{resolved_environment.value}{CONFIG_FILE_SUFFIX}"
        settings = replace(settings, **_read_config_file(config_path))

    settings = replace(settings, **_read_env_overrides(environ))

    _logger.debug("Settings resolved for %s environment: %s", resolved_environment, settings)
    return settings
