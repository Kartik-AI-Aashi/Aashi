"""Smoke-test the PySide6 application bootstrap.

These tests prove the UI-01 success criteria: PySide6 loads, ``QApplication``
initializes, the temporary foundation window builds, and the event loop runs.
They deliberately assert nothing about appearance — there is no design yet.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("pytestqt", reason="pytest-qt is required for GUI smoke tests")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from aashi.app import ApplicationContext, create_application, create_context, run  # noqa: E402
from aashi.config import Environment, Settings  # noqa: E402
from aashi.constants import (  # noqa: E402
    APP_NAME,
    APP_VERSION,
    BOOTSTRAP_WINDOW_MIN_HEIGHT,
    BOOTSTRAP_WINDOW_MIN_WIDTH,
    BOOTSTRAP_WINDOW_TEXT,
    ENV_VAR_DATA_DIR,
    EXIT_CONFIG_ERROR,
    ORGANIZATION_NAME,
)
from aashi.paths import AashiPaths, resolve_paths  # noqa: E402
from aashi.ui.bootstrap import FoundationWindow  # noqa: E402


def test_qapplication_carries_application_metadata(qapp: QApplication) -> None:
    application = create_application([])

    assert application is QApplication.instance()  # Only one per process.
    assert application.applicationName() == APP_NAME
    assert application.applicationVersion() == APP_VERSION
    assert application.organizationName() == ORGANIZATION_NAME


def test_foundation_window_shows_the_expected_text(qtbot) -> None:
    window = FoundationWindow(environment_name=str(Environment.DEVELOPMENT))
    qtbot.addWidget(window)

    assert window.heading_text == BOOTSTRAP_WINDOW_TEXT
    assert window.windowTitle() == APP_NAME
    assert window.minimumWidth() == BOOTSTRAP_WINDOW_MIN_WIDTH
    assert window.minimumHeight() == BOOTSTRAP_WINDOW_MIN_HEIGHT


def test_foundation_window_becomes_visible(qtbot) -> None:
    window = FoundationWindow()
    qtbot.addWidget(window)

    with qtbot.waitExposed(window):
        window.show()

    assert window.isVisible()


def test_create_context_is_qt_free_and_prepares_writable_dirs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The context must resolve without a display and create its own data dirs."""
    monkeypatch.setenv(ENV_VAR_DATA_DIR, str(tmp_path / "userdata"))

    context = create_context(environment=Environment.DEVELOPMENT)

    assert isinstance(context, ApplicationContext)
    assert isinstance(context.settings, Settings)
    assert isinstance(context.paths, AashiPaths)
    assert context.environment is Environment.DEVELOPMENT
    assert context.paths.logs_dir.is_dir()
    assert context.paths.cache_dir.is_dir()


def test_event_loop_starts_and_exits_cleanly(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Run the real entry point, quitting from inside the loop it starts."""
    monkeypatch.setenv(ENV_VAR_DATA_DIR, str(tmp_path / "userdata"))

    # Fires once the event loop is running, which is exactly what we assert.
    QTimer.singleShot(0, qapp.quit)
    exit_code = run(argv=[], environment=Environment.DEVELOPMENT)

    assert exit_code == 0


def test_invalid_configuration_exits_with_config_error_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A broken config file must produce a clean exit code, not a traceback."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "development.toml").write_text('[logging]\nlevel = "LOUD"\n', encoding="utf-8")
    monkeypatch.setenv(ENV_VAR_DATA_DIR, str(tmp_path / "userdata"))
    monkeypatch.setattr(
        "aashi.app.resolve_paths",
        lambda: resolve_paths(
            user_data_dir=tmp_path / "userdata", config_dir=config_dir, env={}
        ),
    )

    assert run(argv=[], environment=Environment.DEVELOPMENT) == EXIT_CONFIG_ERROR
