"""Verify that the package imports and that its metadata is coherent."""

from __future__ import annotations

import importlib
import re
import subprocess
import sys
from importlib import metadata

import pytest

import aashi
from aashi import constants

# Every package that must import cleanly without Qt present.
QT_FREE_MODULES = [
    "aashi",
    "aashi.constants",
    "aashi.paths",
    "aashi.config",
    "aashi.config.environment",
    "aashi.config.settings",
    "aashi.logging_setup",
]

# Package boundaries reserved for future UI modules. They must import even while
# empty, so a later module can fill one in without restructuring anything.
UI_PACKAGE_BOUNDARIES = [
    "aashi.ui",
    "aashi.ui.core",
    "aashi.ui.tokens",
    "aashi.ui.themes",
    "aashi.ui.components",
    "aashi.ui.orb",
    "aashi.ui.icons",
    "aashi.ui.accessibility",
    "aashi.ui.windows",
    "aashi.ui.overlays",
    "aashi.ui.navigation",
    "aashi.ui.models",
    "aashi.ui.services",
    "aashi.ui.utils",
]


@pytest.mark.parametrize("module_name", QT_FREE_MODULES + UI_PACKAGE_BOUNDARIES)
def test_modules_import(module_name: str) -> None:
    assert importlib.import_module(module_name) is not None


def test_version_is_pep440_release() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", aashi.__version__), aashi.__version__


def test_installed_distribution_version_matches_package() -> None:
    """The built distribution must not drift from ``aashi.__version__``."""
    try:
        distribution_version = metadata.version("aashi")
    except metadata.PackageNotFoundError:
        pytest.skip("aashi is not installed; run `pip install -r requirements-dev.txt`")
    assert distribution_version == aashi.__version__


def test_application_identity_constants() -> None:
    assert constants.APP_NAME == "Aashi"
    assert constants.APP_SLUG == "aashi"
    assert constants.APP_VERSION == aashi.__version__
    assert constants.LOGGER_NAMESPACE == constants.APP_SLUG
    assert constants.APP_DESCRIPTION


def test_environment_variable_names_are_namespaced_and_unique() -> None:
    names = [
        constants.ENV_VAR_ENVIRONMENT,
        constants.ENV_VAR_DATA_DIR,
        constants.ENV_VAR_CONFIG_DIR,
        constants.ENV_VAR_LOG_LEVEL,
        constants.ENV_VAR_DEBUG,
    ]
    assert all(name.startswith("AASHI_") for name in names)
    assert len(set(names)) == len(names)


def test_exit_codes_are_distinct() -> None:
    codes = {
        constants.EXIT_SUCCESS,
        constants.EXIT_FAILURE,
        constants.EXIT_CONFIG_ERROR,
    }
    assert len(codes) == 3
    assert constants.EXIT_SUCCESS == 0


def test_importing_aashi_does_not_import_qt() -> None:
    """Importing the package root must stay cheap and Qt-free.

    Guards the boundary that keeps non-GUI consumers, tooling and headless
    subsystems able to import ``aashi`` without starting Qt.
    """
    source = "import sys, aashi; sys.exit(1 if 'PySide6' in sys.modules else 0)"

    result = subprocess.run([sys.executable, "-c", source], check=False)

    assert result.returncode == 0, "importing aashi pulled in PySide6"
