"""Verify the Qt-facing theme engine: token-to-Qt adapters and ThemeManager.

These need a ``QApplication`` and are skipped when pytest-qt is absent, exactly
like the bootstrap smoke tests in ``test_app_bootstrap.py``.

The manager tests only assert behaviour that is independent of the machine
running them: the injected system snapshot is used verbatim at construction,
and fixed modes resolve without consulting the operating system.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pytestqt", reason="pytest-qt is required for GUI tests")

from PySide6.QtCore import QEasingCurve  # noqa: E402
from PySide6.QtGui import QFont  # noqa: E402

from aashi.ui.accessibility.reduced_motion import MotionPreference  # noqa: E402
from aashi.ui.themes.definitions import DARK_THEME, LIGHT_THEME, Theme  # noqa: E402
from aashi.ui.themes.manager import ThemeManager  # noqa: E402
from aashi.ui.themes.mode import ColorScheme, ThemeMode  # noqa: E402
from aashi.ui.themes.qt_adapters import (  # noqa: E402
    build_qpalette,
    to_qcolor,
    to_qeasing_curve,
    to_qfont,
)
from aashi.ui.themes.system import DEFAULT_SYSTEM_PREFERENCES  # noqa: E402
from aashi.ui.tokens.color import Color  # noqa: E402
from aashi.ui.tokens.motion import EASING_ENTRANCE, MotionRole, Duration  # noqa: E402
from aashi.ui.tokens.typography import TextRole, style_for  # noqa: E402


# ---------------------------------------------------------------------------
# Adapters
# ---------------------------------------------------------------------------


def test_to_qcolor_preserves_channels_and_alpha() -> None:
    converted = to_qcolor(Color.from_rgba(11, 13, 18, 0.72))
    assert (converted.red(), converted.green(), converted.blue()) == (11, 13, 18)
    assert converted.alpha() == 184  # round(0.72 * 255)


def test_to_qfont_applies_the_style_metrics() -> None:
    style = style_for(TextRole.BODY)
    font = to_qfont(style)
    assert font.pixelSize() == style.size_px
    assert int(font.weight()) == int(style.weight)
    assert not font.italic()
    families = [family.casefold() for family in font.families()]
    assert style.family[0].casefold() in families


def test_to_qeasing_curve_builds_a_bezier_spline() -> None:
    curve = to_qeasing_curve(EASING_ENTRANCE)
    assert curve.type() == QEasingCurve.Type.BezierSpline


def test_build_qpalette_carries_the_theme_colours() -> None:
    palette = build_qpalette(LIGHT_THEME)
    assert palette.window().color().name() == LIGHT_THEME.palette.surface.canvas.hex
    assert palette.text().color().name() == LIGHT_THEME.palette.text.primary.hex
    assert palette.highlight().color().name() == LIGHT_THEME.palette.accent.base.hex


# ---------------------------------------------------------------------------
# ThemeManager
# ---------------------------------------------------------------------------


def test_manager_creation_uses_the_injected_system_snapshot() -> None:
    manager = ThemeManager(system_reader=lambda: DEFAULT_SYSTEM_PREFERENCES)
    assert manager.mode is ThemeMode.SYSTEM
    assert manager.theme is DARK_THEME  # Default snapshot reports dark.
    assert manager.reduced_motion is False


def test_manager_exposes_the_active_palette_and_scheme() -> None:
    manager = ThemeManager(
        mode=ThemeMode.LIGHT,
        system_reader=lambda: DEFAULT_SYSTEM_PREFERENCES,
    )
    assert manager.palette is LIGHT_THEME.palette
    assert manager.color_scheme is ColorScheme.LIGHT


def test_manager_switching_mode_applies_and_emits_theme_changed(qtbot) -> None:
    manager = ThemeManager(system_reader=lambda: DEFAULT_SYSTEM_PREFERENCES)

    with qtbot.waitSignal(manager.theme_changed, timeout=1000) as blocker:
        manager.set_mode(ThemeMode.LIGHT)

    assert blocker.args == [LIGHT_THEME]
    assert manager.theme is LIGHT_THEME


def test_manager_emits_mode_changed_when_switching_to_system(qtbot) -> None:
    manager = ThemeManager(
        mode=ThemeMode.DARK,
        system_reader=lambda: DEFAULT_SYSTEM_PREFERENCES,
    )

    with qtbot.waitSignal(manager.mode_changed, timeout=1000) as blocker:
        manager.set_mode(ThemeMode.SYSTEM)

    assert blocker.args == ["system"]
    assert manager.mode is ThemeMode.SYSTEM


def test_manager_setting_the_same_mode_is_a_no_op(qtbot) -> None:
    manager = ThemeManager(system_reader=lambda: DEFAULT_SYSTEM_PREFERENCES)

    with qtbot.assertNotEmitted(manager.theme_changed):
        manager.set_mode(ThemeMode.SYSTEM)
    with qtbot.assertNotEmitted(manager.mode_changed):
        manager.set_mode(ThemeMode.SYSTEM)


def test_manager_duration_honours_reduced_motion() -> None:
    manager = ThemeManager(system_reader=lambda: DEFAULT_SYSTEM_PREFERENCES)
    assert manager.duration(MotionRole.SPATIAL) == Duration.SLOW

    manager.set_motion_preference(MotionPreference.REDUCED)

    assert manager.reduced_motion is True
    assert manager.duration(MotionRole.SPATIAL) == Duration.INSTANT


def test_manager_stylesheet_renders_for_the_active_theme() -> None:
    manager = ThemeManager(system_reader=lambda: DEFAULT_SYSTEM_PREFERENCES)
    stylesheet = manager.stylesheet()
    assert "QWidget {" in stylesheet
    assert "{{" not in stylesheet


def test_manager_theme_is_a_concrete_theme() -> None:
    manager = ThemeManager(system_reader=lambda: DEFAULT_SYSTEM_PREFERENCES)
    assert isinstance(manager.theme, Theme)
