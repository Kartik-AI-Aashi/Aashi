"""Verify centralized path resolution."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from aashi.constants import ENV_VAR_CONFIG_DIR, ENV_VAR_DATA_DIR, LOG_FILE_NAME
from aashi.paths import resolve_paths


def test_bundle_locations_derive_from_bundle_root(tmp_path: Path) -> None:
    paths = resolve_paths(bundle_root=tmp_path, user_data_dir=tmp_path / "data", env={})

    assert paths.bundle_root == tmp_path.resolve()
    assert paths.assets_dir == tmp_path.resolve() / "assets"
    assert paths.bundled_config_dir == tmp_path.resolve() / "config"


def test_user_locations_are_nested_under_user_data_dir(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    paths = resolve_paths(bundle_root=tmp_path, user_data_dir=data_dir, env={})

    assert paths.user_data_dir == data_dir.resolve()
    assert paths.logs_dir.parent == data_dir.resolve()
    assert paths.cache_dir.parent == data_dir.resolve()
    assert paths.log_file == paths.logs_dir / LOG_FILE_NAME


def test_all_paths_are_absolute(tmp_path: Path) -> None:
    paths = resolve_paths(bundle_root=tmp_path, user_data_dir=tmp_path / "data", env={})

    for field in dataclasses.fields(paths):
        value = getattr(paths, field.name)
        assert value.is_absolute(), f"{field.name} is not absolute: {value}"


def test_environment_variables_override_defaults(tmp_path: Path) -> None:
    env = {
        ENV_VAR_DATA_DIR: str(tmp_path / "env-data"),
        ENV_VAR_CONFIG_DIR: str(tmp_path / "env-config"),
    }
    paths = resolve_paths(bundle_root=tmp_path, env=env)

    assert paths.user_data_dir == (tmp_path / "env-data").resolve()
    assert paths.bundled_config_dir == (tmp_path / "env-config").resolve()


def test_explicit_arguments_win_over_environment_variables(tmp_path: Path) -> None:
    env = {
        ENV_VAR_DATA_DIR: str(tmp_path / "env-data"),
        ENV_VAR_CONFIG_DIR: str(tmp_path / "env-config"),
    }
    paths = resolve_paths(
        bundle_root=tmp_path,
        user_data_dir=tmp_path / "explicit-data",
        config_dir=tmp_path / "explicit-config",
        env=env,
    )

    assert paths.user_data_dir == (tmp_path / "explicit-data").resolve()
    assert paths.bundled_config_dir == (tmp_path / "explicit-config").resolve()


def test_resolution_creates_no_directories(tmp_path: Path) -> None:
    """Resolving paths must have no filesystem side effects."""
    paths = resolve_paths(bundle_root=tmp_path, user_data_dir=tmp_path / "data", env={})

    assert not paths.user_data_dir.exists()
    assert not paths.logs_dir.exists()
    assert not paths.cache_dir.exists()


def test_ensure_user_directories_is_idempotent(tmp_path: Path) -> None:
    paths = resolve_paths(bundle_root=tmp_path, user_data_dir=tmp_path / "data", env={})

    paths.ensure_user_directories()
    paths.ensure_user_directories()  # Must not raise on the second call.

    for directory in paths.user_directories():
        assert directory.is_dir()


def test_ensure_user_directories_does_not_create_bundle_directories(tmp_path: Path) -> None:
    """A missing assets/config directory is a broken install, not something to create."""
    paths = resolve_paths(
        bundle_root=tmp_path / "missing-bundle",
        user_data_dir=tmp_path / "data",
        env={},
    )
    paths.ensure_user_directories()

    assert not paths.assets_dir.exists()
    assert not paths.bundled_config_dir.exists()


def test_asset_helper_joins_below_assets_dir(tmp_path: Path) -> None:
    paths = resolve_paths(bundle_root=tmp_path, user_data_dir=tmp_path / "data", env={})

    assert paths.asset("icons", "orb.svg") == paths.assets_dir / "icons" / "orb.svg"


def test_config_file_named_after_environment(tmp_path: Path) -> None:
    paths = resolve_paths(bundle_root=tmp_path, user_data_dir=tmp_path / "data", env={})

    assert paths.config_file("development").name == "development.toml"
    assert paths.config_file("production").parent == paths.bundled_config_dir


def test_paths_are_immutable(tmp_path: Path) -> None:
    paths = resolve_paths(bundle_root=tmp_path, user_data_dir=tmp_path / "data", env={})

    with pytest.raises(dataclasses.FrozenInstanceError):
        paths.user_data_dir = tmp_path  # type: ignore[misc]


def test_repository_ships_bundled_configuration() -> None:
    """The real repository layout must expose both environment config files."""
    paths = resolve_paths(env={})
    if not paths.bundled_config_dir.is_dir():
        pytest.skip("not running from a source checkout")

    assert paths.config_file("development").is_file()
    assert paths.config_file("production").is_file()
    assert paths.assets_dir.is_dir()
