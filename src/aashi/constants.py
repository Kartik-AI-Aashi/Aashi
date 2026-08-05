"""Application-wide constants and metadata for Aashi.

Values that identify the application, name its environment variables, or are
otherwise fixed for the lifetime of a build belong here. Nothing in this module
may depend on Qt, on configuration, or on the filesystem.

This module is *not* the home for visual design values. Colours, typography,
spacing, motion durations and similar tokens belong to the design-token module
introduced by a later UI module.
"""

from __future__ import annotations

from aashi import __version__

# ---------------------------------------------------------------------------
# Application identity
# ---------------------------------------------------------------------------

APP_NAME: str = "Aashi"
"""Human-readable application name, shown in UI and window titles."""

APP_SLUG: str = "aashi"
"""Lowercase machine-safe name, used for directories, loggers and imports."""

APP_VERSION: str = __version__
"""Application version, mirroring :data:`aashi.__version__`."""

ORGANIZATION_NAME: str = "Aashi"
"""Organization name reported to Qt; also the per-user data directory name."""

ORGANIZATION_DOMAIN: str = "aashi.local"
"""Reverse-resolvable domain reported to Qt. Local-first, so not a live host."""

APP_DESCRIPTION: str = (
    "A modular, local-first, cloud-enhanced personal AI desktop companion."
)
"""One-line application description, used in metadata and CLI help."""

LOGGER_NAMESPACE: str = APP_SLUG
"""Root logger name. Every Aashi logger is a child of this namespace."""

# ---------------------------------------------------------------------------
# Environment variable names
#
# Centralized so that no module reads a raw environment-variable string.
# ---------------------------------------------------------------------------

ENV_VAR_ENVIRONMENT: str = "AASHI_ENV"
"""Selects the environment: ``development`` or ``production``."""

ENV_VAR_DATA_DIR: str = "AASHI_DATA_DIR"
"""Overrides the per-user writable data directory. Used by tests and portable installs."""

ENV_VAR_CONFIG_DIR: str = "AASHI_CONFIG_DIR"
"""Overrides the directory holding bundled environment configuration files."""

ENV_VAR_LOG_LEVEL: str = "AASHI_LOG_LEVEL"
"""Overrides the configured logging level."""

ENV_VAR_DEBUG: str = "AASHI_DEBUG"
"""Overrides the configured debug flag. Accepts 1/0, true/false, yes/no, on/off."""

# ---------------------------------------------------------------------------
# Filesystem layout names
#
# Directory and file *names* (never absolute paths). Absolute path resolution
# is the sole responsibility of :mod:`aashi.paths`.
# ---------------------------------------------------------------------------

ASSETS_DIR_NAME: str = "assets"
CONFIG_DIR_NAME: str = "config"
LOGS_DIR_NAME: str = "logs"
CACHE_DIR_NAME: str = "cache"

CONFIG_FILE_SUFFIX: str = ".toml"
"""Extension of bundled configuration files, e.g. ``development.toml``."""

LOG_FILE_NAME: str = f"{APP_SLUG}.log"

# ---------------------------------------------------------------------------
# Logging defaults
# ---------------------------------------------------------------------------

LOG_FORMAT: str = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
LOG_DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"
LOG_FILE_MAX_BYTES: int = 1_048_576  # 1 MiB per log file.
LOG_FILE_BACKUP_COUNT: int = 3

# ---------------------------------------------------------------------------
# Exit codes
# ---------------------------------------------------------------------------

EXIT_SUCCESS: int = 0
EXIT_FAILURE: int = 1
EXIT_CONFIG_ERROR: int = 2

# ---------------------------------------------------------------------------
# TEMPORARY — UI-01 bootstrap only
#
# The foundation window exists solely to prove that Python starts, PySide6
# loads, QApplication initializes and the event loop runs. A later UI module
# replaces it with the real Aashi window, at which point this block is deleted.
# ---------------------------------------------------------------------------

BOOTSTRAP_WINDOW_TITLE: str = APP_NAME
BOOTSTRAP_WINDOW_TEXT: str = "Aashi UI Foundation"
BOOTSTRAP_WINDOW_MIN_WIDTH: int = 480
BOOTSTRAP_WINDOW_MIN_HEIGHT: int = 240
