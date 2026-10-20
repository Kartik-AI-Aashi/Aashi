"""Centralized path management for Aashi.

Every filesystem location used by the application is resolved here. No other
module may construct absolute paths, so that packaging, relocation and testing
each require a change in exactly one place.

Two families of locations exist:

*Read-only bundle locations* — assets and bundled configuration. These ship with
the application. When running from source they resolve inside the repository;
when running from a frozen build they resolve next to the executable (or inside
the PyInstaller extraction directory).

*Per-user writable locations* — application data, logs and cache. On Windows
these live under ``%LOCALAPPDATA%\\Aashi``, which is the correct location for
machine-local application data and needs no elevation. Other platforms follow
the XDG convention so that development on non-Windows hosts behaves sensibly.

Nothing here creates directories on import. Writable directories are created
only when :meth:`AashiPaths.ensure_user_directories` is called explicitly.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from aashi.constants import (
    ASSETS_DIR_NAME,
    CACHE_DIR_NAME,
    CONFIG_DIR_NAME,
    ENV_VAR_CONFIG_DIR,
    ENV_VAR_DATA_DIR,
    LOG_FILE_NAME,
    LOGS_DIR_NAME,
    ORGANIZATION_NAME,
)

__all__ = ["AashiPaths", "is_frozen", "resolve_paths"]


def is_frozen() -> bool:
    """Return ``True`` when running from a frozen/packaged build.

    Frozen builds are detected via the ``sys.frozen`` attribute set by
    PyInstaller and comparable tools.
    """
    return bool(getattr(sys, "frozen", False))


def _bundle_root() -> Path:
    """Return the directory that read-only bundled resources live under."""
    if is_frozen():
        # PyInstaller one-file builds extract to a temporary directory exposed
        # as sys._MEIPASS; one-folder builds ship resources beside the binary.
        extraction_dir = getattr(sys, "_MEIPASS", None)
        if extraction_dir:
            return Path(extraction_dir)
        return Path(sys.executable).resolve().parent
    # Source layout: <root>/src/aashi/paths.py -> <root>.  A wheel/frozen
    # package carries the small runtime config bundle inside the package,
    # because top-level repository folders are not importable resources.
    source_root = Path(__file__).resolve().parents[2]
    if (source_root / CONFIG_DIR_NAME).is_dir():
        return source_root
    packaged_root = Path(__file__).resolve().parent / "bundled"
    if (packaged_root / CONFIG_DIR_NAME).is_dir():
        return packaged_root
    return source_root


def _default_user_data_root() -> Path:
    """Return the platform-appropriate per-user writable data directory."""
    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
        return base / ORGANIZATION_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / ORGANIZATION_NAME
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg_data_home) if xdg_data_home else Path.home() / ".local" / "share"
    return base / ORGANIZATION_NAME


@dataclass(frozen=True, slots=True)
class AashiPaths:
    """Resolved, absolute filesystem locations for one application run.

    Instances are immutable and cheap to pass around. Construct them with
    :func:`resolve_paths` rather than directly, unless a test needs full
    control over every field.
    """

    bundle_root: Path
    """Root of read-only bundled resources (repository root, or install dir)."""

    assets_dir: Path
    """Bundled static assets: icons, fonts, images."""

    bundled_config_dir: Path
    """Directory holding the environment configuration files that ship with Aashi."""

    user_data_dir: Path
    """Per-user writable root for everything Aashi persists."""

    logs_dir: Path
    """Per-user writable directory for log files."""

    cache_dir: Path
    """Per-user writable directory for regenerable data. Safe to delete."""

    @property
    def log_file(self) -> Path:
        """Absolute path of the main rotating log file."""
        return self.logs_dir / LOG_FILE_NAME

    def config_file(self, environment_name: str, suffix: str = ".toml") -> Path:
        """Return the bundled configuration file for ``environment_name``.

        The file is not required to exist; callers decide whether a missing
        configuration file is an error or simply means "use defaults".
        """
        return self.bundled_config_dir / f"{environment_name}{suffix}"

    def asset(self, *parts: str) -> Path:
        """Return an absolute path to a bundled asset.

        Example: ``paths.asset("icons", "orb.svg")``.
        """
        return self.assets_dir.joinpath(*parts)

    def user_directories(self) -> tuple[Path, ...]:
        """Return the writable directories Aashi owns, outermost first."""
        return (self.user_data_dir, self.logs_dir, self.cache_dir)

    def ensure_user_directories(self) -> None:
        """Create the per-user writable directories if they do not yet exist.

        Idempotent. Read-only bundle directories are never created; a missing
        assets or config directory indicates a broken installation and must
        surface as an error rather than being silently papered over.
        """
        for directory in self.user_directories():
            directory.mkdir(parents=True, exist_ok=True)


def resolve_paths(
    *,
    bundle_root: Path | None = None,
    user_data_dir: Path | None = None,
    config_dir: Path | None = None,
    env: dict[str, str] | None = None,
) -> AashiPaths:
    """Resolve all application paths for the current run.

    Precedence for each overridable location is: explicit argument, then
    environment variable, then platform default.

    Args:
        bundle_root: Overrides detection of the read-only bundle root.
        user_data_dir: Overrides the per-user writable root.
        config_dir: Overrides the bundled configuration directory.
        env: Environment mapping to read overrides from. Defaults to
            ``os.environ``. Injectable so tests never mutate real environment
            state.

    Returns:
        An immutable :class:`AashiPaths` with absolute, expanded paths.
    """
    environ = os.environ if env is None else env

    root = (bundle_root or _bundle_root()).expanduser().resolve()

    if user_data_dir is not None:
        data_root = user_data_dir
    elif environ.get(ENV_VAR_DATA_DIR):
        data_root = Path(environ[ENV_VAR_DATA_DIR])
    else:
        data_root = _default_user_data_root()
    data_root = data_root.expanduser().resolve()

    if config_dir is not None:
        bundled_config = config_dir
    elif environ.get(ENV_VAR_CONFIG_DIR):
        bundled_config = Path(environ[ENV_VAR_CONFIG_DIR])
    else:
        bundled_config = root / CONFIG_DIR_NAME
    bundled_config = bundled_config.expanduser().resolve()

    return AashiPaths(
        bundle_root=root,
        assets_dir=root / ASSETS_DIR_NAME,
        bundled_config_dir=bundled_config,
        user_data_dir=data_root,
        logs_dir=data_root / LOGS_DIR_NAME,
        cache_dir=data_root / CACHE_DIR_NAME,
    )
