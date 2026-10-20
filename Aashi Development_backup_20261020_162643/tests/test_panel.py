"""Verify the UI-02B panel component.

Creation, the two variants, the two border weights, token-driven radius and
padding, and re-styling when the theme changes.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pytestqt", reason="pytest-qt is required for GUI tests")

from aashi.ui.components.panel import AashiPanel, PanelBorder, PanelVariant  # noqa: E402
from aashi.ui.themes.definitions import DARK_THEME, LIGHT_THEME  # noqa: E402
from aashi.ui.themes.manager import ThemeManager  # noqa: E402
from aashi.ui.themes.mode import ColorScheme, ThemeMode  # noqa: E402
from aashi.ui.themes.qss import qss_variables  # noqa: E402
from aashi.ui.themes.system import SystemPreferences  # noqa: E402
from aashi.ui.tokens.spacing import Space  # noqa: E402


def _manager() -> ThemeManager:
    return ThemeManager(system_reader=lambda: SystemPreferences(
        color_scheme=ColorScheme.DARK,
        high_contrast=False,
        reduced_motion=False,
    ))


@pytest.mark.parametrize("variant", list(PanelVariant))
def test_panel_builds_for_every_variant(qtbot, variant: PanelVariant) -> None:
    panel = AashiPanel(_manager(), variant=variant)
    qtbot.addWidget(panel)

    assert panel.variant is variant
    assert panel.styleSheet()


def test_elevated_and_flat_use_their_surface_fills(qtbot) -> None:
    elevated = AashiPanel(_manager(), variant=PanelVariant.ELEVATED)
    qtbot.addWidget(elevated)
    assert DARK_THEME.palette.surface.elevated.css in elevated.styleSheet()

    flat = AashiPanel(_manager(), variant=PanelVariant.FLAT)
    qtbot.addWidget(flat)
    assert DARK_THEME.palette.surface.primary.css in flat.styleSheet()


def test_hairline_and_strong_borders_use_their_colours(qtbot) -> None:
    hairline = AashiPanel(_manager(), border=PanelBorder.HAIRLINE)
    qtbot.addWidget(hairline)
    assert DARK_THEME.palette.border.subtle.css in hairline.styleSheet()

    strong = AashiPanel(_manager(), border=PanelBorder.STRONG)
    qtbot.addWidget(strong)
    assert DARK_THEME.palette.border.strong.css in strong.styleSheet()


def test_radius_and_padding_come_from_tokens(qtbot) -> None:
    panel = AashiPanel(_manager())
    qtbot.addWidget(panel)

    variables = qss_variables(DARK_THEME)
    assert f"border-radius: {variables['radius.medium']};" in panel.styleSheet()
    margins = panel.layout().contentsMargins()
    assert margins.left() == Space.SPACE_300.value
    assert margins.top() == Space.SPACE_300.value


def test_panel_restyles_when_the_theme_changes(qtbot) -> None:
    manager = _manager()
    panel = AashiPanel(manager, variant=PanelVariant.ELEVATED)
    qtbot.addWidget(panel)
    assert DARK_THEME.palette.surface.elevated.css in panel.styleSheet()

    manager.set_mode(ThemeMode.LIGHT)

    assert LIGHT_THEME.palette.surface.elevated.css in panel.styleSheet()


def test_set_variant_rebuilds_the_stylesheet(qtbot) -> None:
    panel = AashiPanel(_manager(), variant=PanelVariant.ELEVATED)
    qtbot.addWidget(panel)

    panel.set_variant(PanelVariant.FLAT)

    assert panel.variant is PanelVariant.FLAT
    assert DARK_THEME.palette.surface.primary.css in panel.styleSheet()


def test_set_border_rebuilds_the_stylesheet(qtbot) -> None:
    panel = AashiPanel(_manager(), border=PanelBorder.HAIRLINE)
    qtbot.addWidget(panel)

    panel.set_border(PanelBorder.STRONG)

    assert panel.border is PanelBorder.STRONG
    assert DARK_THEME.palette.border.strong.css in panel.styleSheet()


def test_high_contrast_forces_a_permanent_outline(qtbot) -> None:
    manager = ThemeManager(system_reader=lambda: SystemPreferences(
        color_scheme=ColorScheme.DARK,
        high_contrast=True,
        reduced_motion=False,
    ))
    panel = AashiPanel(manager, border=PanelBorder.HAIRLINE)
    qtbot.addWidget(panel)

    assert manager.theme.high_contrast
    assert manager.theme.palette.border.strong.css in panel.styleSheet()
