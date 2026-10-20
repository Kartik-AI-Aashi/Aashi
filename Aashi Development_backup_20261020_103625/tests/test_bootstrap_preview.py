"""Verify the theme-preview extension of the temporary foundation window.

The preview is scaffolding, not the real interface, but it is the only UI that
exercises the theme engine end to end. These tests cover creation, following
theme changes, the reduced-motion toggle and the mode buttons' signal wiring.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pytestqt", reason="pytest-qt is required for GUI tests")

from PySide6.QtCore import Qt  # noqa: E402

from aashi.ui.accessibility.reduced_motion import MotionPreference  # noqa: E402
from aashi.ui.bootstrap import FoundationWindow  # noqa: E402
from aashi.ui.themes.definitions import LIGHT_THEME  # noqa: E402
from aashi.ui.themes.manager import ThemeManager  # noqa: E402
from aashi.ui.themes.mode import ThemeMode  # noqa: E402
from aashi.ui.themes.system import DEFAULT_SYSTEM_PREFERENCES  # noqa: E402


def _manager() -> ThemeManager:
    return ThemeManager(system_reader=lambda: DEFAULT_SYSTEM_PREFERENCES)


def test_preview_window_builds_with_a_theme_manager(qtbot) -> None:
    window = FoundationWindow(theme_manager=_manager())
    qtbot.addWidget(window)

    assert "theme: dark" in window.status_text


def test_preview_follows_theme_changes(qtbot) -> None:
    manager = _manager()
    window = FoundationWindow(theme_manager=manager)
    qtbot.addWidget(window)

    manager.set_mode(ThemeMode.LIGHT)

    assert manager.theme is LIGHT_THEME
    assert "theme: light" in window.status_text


def test_preview_reduced_motion_toggle_updates_the_status(qtbot) -> None:
    manager = _manager()
    window = FoundationWindow(theme_manager=manager)
    qtbot.addWidget(window)

    manager.set_motion_preference(MotionPreference.REDUCED)

    assert "reduced motion: True" in window.status_text


def test_preview_mode_button_switches_the_theme(qtbot) -> None:
    manager = _manager()
    window = FoundationWindow(theme_manager=manager)
    qtbot.addWidget(window)

    light_button = window._mode_buttons.buttons()[1]  # Dark, Light, System
    qtbot.mouseClick(light_button, Qt.MouseButton.LeftButton)

    assert manager.mode is ThemeMode.LIGHT
    assert "theme: light" in window.status_text
