"""Verify environment detection and the layered configuration foundation."""

from __future__ import annotations

import dataclasses
import logging
from pathlib import Path

import pytest

from aashi.config import ConfigError, Environment, Settings, detect_environment, load_settings
from aashi.constants import ENV_VAR_DEBUG, ENV_VAR_ENVIRONMENT, ENV_VAR_LOG_LEVEL


def write_config(directory: Path, environment: Environment, body: str) -> Path:
    """Write a bundled configuration file and return its path."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{environment.value}.toml"
    path.write_text(body, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Environment detection
# ---------------------------------------------------------------------------


def test_source_runs_default_to_development() -> None:
    assert detect_environment(env={}) is Environment.DEVELOPMENT


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("development", Environment.DEVELOPMENT),
        ("dev", Environment.DEVELOPMENT),
        ("DEV", Environment.DEVELOPMENT),
        ("  Development  ", Environment.DEVELOPMENT),
        ("production", Environment.PRODUCTION),
        ("prod", Environment.PRODUCTION),
        ("PRODUCTION", Environment.PRODUCTION),
        ("release", Environment.PRODUCTION),
    ],
)
def test_environment_variable_aliases(raw_value: str, expected: Environment) -> None:
    assert detect_environment(env={ENV_VAR_ENVIRONMENT: raw_value}) is expected


def test_unrecognized_environment_falls_back_instead_of_failing() -> None:
    """A typo in AASHI_ENV must never stop Aashi from starting."""
    assert detect_environment(env={ENV_VAR_ENVIRONMENT: "staging"}) is Environment.DEVELOPMENT


def test_environment_predicates_and_string_value() -> None:
    assert Environment.DEVELOPMENT.is_development
    assert not Environment.DEVELOPMENT.is_production
    assert Environment.PRODUCTION.is_production
    assert str(Environment.PRODUCTION) == "production"


# ---------------------------------------------------------------------------
# Defaults per environment
# ---------------------------------------------------------------------------


def test_development_defaults_favour_diagnostics() -> None:
    settings = load_settings(environment=Environment.DEVELOPMENT, env={})

    assert settings.environment is Environment.DEVELOPMENT
    assert settings.debug is True
    assert settings.log_level == "DEBUG"
    assert settings.log_to_console is True


def test_production_defaults_are_quiet_and_not_debug() -> None:
    settings = load_settings(environment=Environment.PRODUCTION, env={})

    assert settings.environment is Environment.PRODUCTION
    assert settings.debug is False
    assert settings.log_level == "INFO"
    # Packaged Windows builds have no console attached.
    assert settings.log_to_console is False


def test_numeric_log_level_matches_logging_module() -> None:
    settings = load_settings(environment=Environment.PRODUCTION, env={})

    assert settings.numeric_log_level == logging.INFO


def test_settings_are_immutable() -> None:
    settings = load_settings(environment=Environment.DEVELOPMENT, env={})

    with pytest.raises(dataclasses.FrozenInstanceError):
        settings.debug = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# File layer
# ---------------------------------------------------------------------------


def test_missing_config_file_is_not_an_error(tmp_path: Path) -> None:
    settings = load_settings(environment=Environment.PRODUCTION, config_dir=tmp_path, env={})

    assert settings == Settings(
        environment=Environment.PRODUCTION,
        debug=False,
        log_level="INFO",
        log_to_console=False,
        log_to_file=True,
    )


def test_config_file_overrides_defaults(tmp_path: Path) -> None:
    write_config(
        tmp_path,
        Environment.PRODUCTION,
        """
        [app]
        debug = true

        [logging]
        level = "warning"
        console = true
        file = false
        """,
    )

    settings = load_settings(environment=Environment.PRODUCTION, config_dir=tmp_path, env={})

    assert settings.debug is True
    assert settings.log_level == "WARNING"  # Normalized to upper case.
    assert settings.log_to_console is True
    assert settings.log_to_file is False


def test_only_the_active_environment_file_is_read(tmp_path: Path) -> None:
    write_config(tmp_path, Environment.DEVELOPMENT, '[logging]\nlevel = "CRITICAL"\n')
    write_config(tmp_path, Environment.PRODUCTION, '[logging]\nlevel = "ERROR"\n')

    settings = load_settings(environment=Environment.PRODUCTION, config_dir=tmp_path, env={})

    assert settings.log_level == "ERROR"


def test_unknown_table_is_ignored_for_future_modules(tmp_path: Path) -> None:
    """Later modules must be able to add their own sections without edits here."""
    write_config(
        tmp_path,
        Environment.DEVELOPMENT,
        """
        [logging]
        level = "ERROR"

        [voice]
        wake_word = "aashi"
        """,
    )

    settings = load_settings(environment=Environment.DEVELOPMENT, config_dir=tmp_path, env={})

    assert settings.log_level == "ERROR"


def test_unknown_key_in_known_table_raises(tmp_path: Path) -> None:
    """Typos inside a table we own must surface at startup."""
    write_config(tmp_path, Environment.DEVELOPMENT, '[logging]\nlevle = "DEBUG"\n')

    with pytest.raises(ConfigError, match="unknown key"):
        load_settings(environment=Environment.DEVELOPMENT, config_dir=tmp_path, env={})


def test_invalid_toml_raises(tmp_path: Path) -> None:
    write_config(tmp_path, Environment.DEVELOPMENT, "[logging\nlevel = DEBUG")

    with pytest.raises(ConfigError, match="invalid TOML"):
        load_settings(environment=Environment.DEVELOPMENT, config_dir=tmp_path, env={})


def test_invalid_log_level_raises(tmp_path: Path) -> None:
    write_config(tmp_path, Environment.DEVELOPMENT, '[logging]\nlevel = "CHATTY"\n')

    with pytest.raises(ConfigError, match="unknown log level"):
        load_settings(environment=Environment.DEVELOPMENT, config_dir=tmp_path, env={})


def test_non_boolean_debug_value_raises(tmp_path: Path) -> None:
    write_config(tmp_path, Environment.DEVELOPMENT, "[app]\ndebug = 3\n")

    with pytest.raises(ConfigError, match="expected a boolean"):
        load_settings(environment=Environment.DEVELOPMENT, config_dir=tmp_path, env={})


# ---------------------------------------------------------------------------
# Environment variable layer
# ---------------------------------------------------------------------------


def test_environment_variables_override_the_config_file(tmp_path: Path) -> None:
    write_config(
        tmp_path,
        Environment.DEVELOPMENT,
        '[app]\ndebug = true\n\n[logging]\nlevel = "DEBUG"\n',
    )

    settings = load_settings(
        environment=Environment.DEVELOPMENT,
        config_dir=tmp_path,
        env={ENV_VAR_LOG_LEVEL: "error", ENV_VAR_DEBUG: "off"},
    )

    assert settings.log_level == "ERROR"
    assert settings.debug is False


@pytest.mark.parametrize("raw_value", ["1", "true", "TRUE", "yes", "on"])
def test_truthy_debug_spellings(raw_value: str) -> None:
    settings = load_settings(environment=Environment.PRODUCTION, env={ENV_VAR_DEBUG: raw_value})

    assert settings.debug is True


@pytest.mark.parametrize("raw_value", ["0", "false", "FALSE", "no", "off"])
def test_falsy_debug_spellings(raw_value: str) -> None:
    settings = load_settings(environment=Environment.DEVELOPMENT, env={ENV_VAR_DEBUG: raw_value})

    assert settings.debug is False


def test_invalid_debug_environment_variable_raises() -> None:
    with pytest.raises(ConfigError, match="expected a boolean"):
        load_settings(environment=Environment.DEVELOPMENT, env={ENV_VAR_DEBUG: "maybe"})


def test_environment_is_detected_when_not_supplied() -> None:
    settings = load_settings(env={ENV_VAR_ENVIRONMENT: "prod"})

    assert settings.environment is Environment.PRODUCTION
