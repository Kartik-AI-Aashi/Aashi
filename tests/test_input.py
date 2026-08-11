"""Verify the UI-02B input component.

Creation, token-driven surface and geometry, placeholder styling through the
``PlaceholderText`` palette role, the focus ring, the disabled state, and
re-styling when the theme changes.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pytestqt", reason="pytest-qt is required for GUI tests")

from PySide6.QtGui import QPalette  # noqa: E402

from aashi.ui.components.input import AashiInput  # noqa: E402
from aashi.ui.themes.definitions import DARK_THEME, LIGHT_THEME  # noqa: E402
from aashi.ui.themes.manager import ThemeManager  # noqa: E402
from aashi.ui.themes.mode import ColorScheme, ThemeMode  # noqa: E402
from aashi.ui.themes.qss import qss_variables  # noqa: E402
from aashi.ui.themes.qt_adapters import to_qcolor  # noqa: E402
from aashi.ui.themes.system import SystemPreferences  # noqa: E402


def _manager() -> ThemeManager:
    return ThemeManager(system_reader=lambda: SystemPreferences(
        color_scheme=ColorScheme.DARK,
        high_contrast=False,
        reduced_motion=False,
    ))


def test_input_builds_with_placeholder(qtbot) -> None:
    input_ = AashiInput(_manager(), placeholder="Search")
    qtbot.addWidget(input_)

    assert input_.placeholderText() == "Search"
    assert input_.styleSheet()


def test_input_uses_the_recessed_surface_and_text_colours(qtbot) -> None:
    input_ = AashiInput(_manager(), placeholder="Name")
    qtbot.addWidget(input_)

    stylesheet = input_.styleSheet()
    assert DARK_THEME.palette.surface.nested.css in stylesheet
    assert DARK_THEME.palette.text.primary.css in stylesheet


def test_radius_padding_and_height_come_from_tokens(qtbot) -> None:
    input_ = AashiInput(_manager())
    qtbot.addWidget(input_)

    variables = qss_variables(DARK_THEME)
    stylesheet = input_.styleSheet()
    assert f"border-radius: {variables['radius.large']};" in stylesheet
    assert f"padding: 0 {variables['space.300']};" in stylesheet
    assert f"min-height: {variables['control.height.large']};" in stylesheet


def test_focus_ring_uses_the_focus_border_token(qtbot) -> None:
    input_ = AashiInput(_manager())
    qtbot.addWidget(input_)

    variables = qss_variables(DARK_THEME)
    assert (
        f"border: {variables['border.focusRing']} solid "
        f"{variables['color.border.focus']};"
        in input_.styleSheet()
    )


def test_placeholder_styled_through_the_placeholder_text_palette_role(qtbot) -> None:
    input_ = AashiInput(_manager(), placeholder="Search")
    qtbot.addWidget(input_)

    colour = input_.palette().color(QPalette.ColorRole.PlaceholderText)
    assert colour == to_qcolor(DARK_THEME.palette.text.tertiary)


def test_disabled_uses_the_disabled_text_colour(qtbot) -> None:
    input_ = AashiInput(_manager(), placeholder="Name")
    qtbot.addWidget(input_)
    input_.setEnabled(False)

    assert DARK_THEME.palette.text.tertiary.css in input_.styleSheet()


def test_input_restyles_when_the_theme_changes(qtbot) -> None:
    manager = _manager()
    input_ = AashiInput(manager, placeholder="Search")
    qtbot.addWidget(input_)
    assert DARK_THEME.palette.surface.nested.css in input_.styleSheet()

    manager.set_mode(ThemeMode.LIGHT)

    assert LIGHT_THEME.palette.surface.nested.css in input_.styleSheet()
    colour = input_.palette().color(QPalette.ColorRole.PlaceholderText)
    assert colour == to_qcolor(LIGHT_THEME.palette.text.tertiary)


def test_high_contrast_forces_a_permanent_outline(qtbot) -> None:
    manager = ThemeManager(system_reader=lambda: SystemPreferences(
        color_scheme=ColorScheme.DARK,
        high_contrast=True,
        reduced_motion=False,
    ))
    input_ = AashiInput(manager, placeholder="Name")
    qtbot.addWidget(input_)

    assert manager.theme.high_contrast
    assert manager.theme.palette.border.strong.css in input_.styleSheet()


def test_input_accepts_typing(qtbot) -> None:
    input_ = AashiInput(_manager())
    qtbot.addWidget(input_)

    qtbot.keyClicks(input_, "Aashi")

    assert input_.text() == "Aashi"
