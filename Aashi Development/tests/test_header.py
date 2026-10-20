"""Verify the UI-02B header component.

Creation, the default and custom titles, the title typography role, the primary
surface fill, the hairline separator, token-driven padding and spacing, and
re-styling when the theme changes.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pytestqt", reason="pytest-qt is required for GUI tests")

from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import QLabel  # noqa: E402

from aashi.constants import APP_NAME  # noqa: E402
from aashi.ui.components.header import AashiHeader  # noqa: E402
from aashi.ui.themes.definitions import DARK_THEME, LIGHT_THEME  # noqa: E402
from aashi.ui.themes.manager import ThemeManager  # noqa: E402
from aashi.ui.themes.mode import ColorScheme, ThemeMode  # noqa: E402
from aashi.ui.themes.qss import qss_variables  # noqa: E402
from aashi.ui.themes.system import SystemPreferences  # noqa: E402
from aashi.ui.tokens.spacing import SPACING  # noqa: E402
from aashi.ui.tokens.typography import TextRole, style_for  # noqa: E402


def _manager() -> ThemeManager:
    return ThemeManager(system_reader=lambda: SystemPreferences(
        color_scheme=ColorScheme.DARK,
        high_contrast=False,
        reduced_motion=False,
    ))


def test_header_builds_with_the_app_name(qtbot) -> None:
    header = AashiHeader(_manager())
    qtbot.addWidget(header)

    assert header.title == APP_NAME
    assert header.styleSheet()


def test_header_shows_a_custom_title_and_replaces_it(qtbot) -> None:
    header = AashiHeader(_manager(), title="Messages")
    qtbot.addWidget(header)
    assert header.title == "Messages"

    header.set_title("Tasks")
    assert header.title == "Tasks"


def test_title_uses_the_title_typography_role(qtbot) -> None:
    header = AashiHeader(_manager())
    qtbot.addWidget(header)

    label = header.findChild(QLabel)
    style = style_for(TextRole.TITLE)
    assert label.font().pixelSize() == style.size_px
    assert label.font().weight() == QFont.Weight(int(style.weight))


def test_background_and_title_colours_come_from_the_primary_surface(qtbot) -> None:
    header = AashiHeader(_manager())
    qtbot.addWidget(header)

    stylesheet = header.styleSheet()
    assert DARK_THEME.palette.surface.primary.css in stylesheet
    assert DARK_THEME.palette.text.primary.css in stylesheet


def test_bottom_border_uses_the_hairline_separator_tokens(qtbot) -> None:
    header = AashiHeader(_manager())
    qtbot.addWidget(header)

    variables = qss_variables(DARK_THEME)
    assert (
        f"border-bottom: {variables['border.hairline']} solid "
        f"{variables['color.border']};"
        in header.styleSheet()
    )


def test_padding_and_spacing_come_from_spacing_tokens(qtbot) -> None:
    header = AashiHeader(_manager())
    qtbot.addWidget(header)

    margins = header.layout().contentsMargins()
    assert margins.left() == SPACING.gutter_compact
    assert margins.right() == SPACING.gutter_compact
    assert margins.top() == SPACING.control_padding_vertical
    assert margins.bottom() == SPACING.control_padding_vertical
    assert header.layout().spacing() == SPACING.inline_gap


def test_header_restyles_when_the_theme_changes(qtbot) -> None:
    manager = _manager()
    header = AashiHeader(manager)
    qtbot.addWidget(header)
    assert DARK_THEME.palette.surface.primary.css in header.styleSheet()

    manager.set_mode(ThemeMode.LIGHT)

    assert LIGHT_THEME.palette.surface.primary.css in header.styleSheet()


def test_high_contrast_keeps_a_visible_separator(qtbot) -> None:
    manager = ThemeManager(system_reader=lambda: SystemPreferences(
        color_scheme=ColorScheme.DARK,
        high_contrast=True,
        reduced_motion=False,
    ))
    header = AashiHeader(manager)
    qtbot.addWidget(header)

    assert manager.theme.high_contrast
    # High contrast collapses every surface onto the canvas, so the bottom
    # hairline is the only thing separating the header from the content.
    assert manager.theme.palette.border.subtle.css in header.styleSheet()
