"""Verify theme-mode resolution, the theme definitions, QSS substitution and
the system-preferences snapshot.

Everything here is Qt-free; the Qt-facing parts (ThemeManager, adapters and the
preview window) are covered in ``test_theme_manager.py`` and
``test_bootstrap_preview.py``.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from aashi.ui.tokens.borders import FOCUS_RING_MIN_CONTRAST
from aashi.ui.tokens.color import contrast_ratio
from aashi.ui.themes.definitions import (
    ALL_THEMES,
    DARK_THEME,
    HIGH_CONTRAST_THEME,
    LIGHT_THEME,
    theme_for,
)
from aashi.ui.themes.mode import ColorScheme, ThemeMode
from aashi.ui.themes.qss import (
    QssTemplateError,
    build_base_stylesheet,
    qss_variables,
    render_qss,
)
from aashi.ui.themes.system import SystemPreferences, read_system_preferences


# ---------------------------------------------------------------------------
# Theme mode
# ---------------------------------------------------------------------------


def test_theme_mode_parse_accepts_any_case_and_whitespace() -> None:
    assert ThemeMode.parse("Dark") is ThemeMode.DARK
    assert ThemeMode.parse(" system ") is ThemeMode.SYSTEM


def test_theme_mode_parse_rejects_unknown_names() -> None:
    with pytest.raises(ValueError):
        ThemeMode.parse("sepia")


def test_theme_mode_resolves_only_system_against_the_os() -> None:
    assert ThemeMode.DARK.resolve(ColorScheme.LIGHT) is ColorScheme.DARK
    assert ThemeMode.LIGHT.resolve(ColorScheme.DARK) is ColorScheme.LIGHT
    assert ThemeMode.SYSTEM.resolve(ColorScheme.DARK) is ColorScheme.DARK
    assert ThemeMode.SYSTEM.resolve(ColorScheme.LIGHT) is ColorScheme.LIGHT
    assert ThemeMode.DARK.is_fixed


# ---------------------------------------------------------------------------
# Theme definitions
# ---------------------------------------------------------------------------


def test_three_themes_are_defined() -> None:
    assert set(ALL_THEMES) == {"dark", "light", "high-contrast"}


def test_dark_and_light_themes_satisfy_their_schemes() -> None:
    assert DARK_THEME.is_dark
    assert not LIGHT_THEME.is_dark
    assert DARK_THEME.scheme is ColorScheme.DARK
    assert LIGHT_THEME.scheme is ColorScheme.LIGHT


def test_theme_for_selects_by_scheme() -> None:
    assert theme_for(ColorScheme.DARK) is DARK_THEME
    assert theme_for(ColorScheme.LIGHT) is LIGHT_THEME


def test_high_contrast_overrides_the_scheme() -> None:
    for scheme in (ColorScheme.DARK, ColorScheme.LIGHT):
        assert theme_for(scheme, high_contrast=True) is HIGH_CONTRAST_THEME


def test_high_contrast_theme_disables_translucency() -> None:
    assert HIGH_CONTRAST_THEME.high_contrast
    assert not HIGH_CONTRAST_THEME.allows_translucency


# ---------------------------------------------------------------------------
# WCAG contrast, promised by the specification comments in definitions.py
# ---------------------------------------------------------------------------


def test_every_theme_passes_aa_for_body_text_on_its_canvas() -> None:
    for theme in ALL_THEMES.values():
        ratio = contrast_ratio(theme.palette.text.primary, theme.palette.surface.canvas)
        assert ratio >= 4.5, f"{theme.name}: primary text {ratio:.2f}:1 on canvas"


def test_every_theme_focus_ring_meets_non_text_contrast() -> None:
    for theme in ALL_THEMES.values():
        ratio = contrast_ratio(theme.palette.border.focus, theme.palette.surface.nested)
        assert ratio >= FOCUS_RING_MIN_CONTRAST, f"{theme.name}: focus ring {ratio:.2f}:1"


def test_every_status_text_role_meets_aa_on_the_primary_surface() -> None:
    for theme in ALL_THEMES.values():
        for role in ("success", "warning", "danger", "information"):
            colour = getattr(theme.palette.status, role).text
            ratio = contrast_ratio(colour, theme.palette.surface.primary)
            assert ratio >= 4.5, f"{theme.name}/{role}: {ratio:.2f}:1"


# ---------------------------------------------------------------------------
# QSS engine
# ---------------------------------------------------------------------------


def test_qss_variables_include_theme_colours_and_geometry() -> None:
    variables = qss_variables(DARK_THEME)
    assert variables["color.surface"] == DARK_THEME.palette.surface.primary.css
    assert variables["color.accent"] == DARK_THEME.palette.accent.base.css
    assert variables["border.hairline"] == "1px"
    assert variables["radius.medium"] == "8px"


def test_render_qss_substitutes_tokens() -> None:
    rendered = render_qss("background: {{color.surface}};", DARK_THEME)
    assert rendered == f"background: {DARK_THEME.palette.surface.primary.css};"


def test_render_qss_raises_on_an_unknown_token() -> None:
    with pytest.raises(QssTemplateError, match="color.nope"):
        render_qss("background: {{color.nope}};", DARK_THEME)


def test_render_qss_names_every_unknown_token_at_once() -> None:
    with pytest.raises(QssTemplateError) as excinfo:
        render_qss("{{color.nope}} {{font.missing}}", DARK_THEME)
    message = str(excinfo.value)
    assert "color.nope" in message
    assert "font.missing" in message


def test_base_stylesheet_renders_for_every_theme() -> None:
    for theme in ALL_THEMES.values():
        stylesheet = build_base_stylesheet(theme)
        assert "QWidget {" in stylesheet
        assert "{{" not in stylesheet  # No placeholder left behind.


# ---------------------------------------------------------------------------
# System preferences
# ---------------------------------------------------------------------------


def test_system_preferences_hold_a_coherent_snapshot() -> None:
    preferences = SystemPreferences(
        color_scheme=ColorScheme.DARK,
        high_contrast=True,
        reduced_motion=False,
    )
    assert preferences.color_scheme is ColorScheme.DARK
    assert preferences.high_contrast is True
    assert preferences.reduced_motion is False


def test_read_system_preferences_returns_a_snapshot() -> None:
    preferences = read_system_preferences()
    assert preferences.color_scheme in (ColorScheme.DARK, ColorScheme.LIGHT)
    assert isinstance(preferences.high_contrast, bool)
    assert isinstance(preferences.reduced_motion, bool)


# ---------------------------------------------------------------------------
# Qt-free boundary
# ---------------------------------------------------------------------------


def test_token_theme_and_accessibility_layers_stay_qt_free() -> None:
    """Importing the value layers must never pull in PySide6.

    Documented contract in ``aashi.ui.tokens`` and ``aashi.ui.themes``; checked
    in a subprocess because pytest-qt imports PySide6 into this process.
    """
    source = (
        "import aashi.ui.tokens, aashi.ui.themes, aashi.ui.accessibility; "
        "import sys; sys.exit(1 if 'PySide6' in sys.modules else 0)"
    )
    result = subprocess.run([sys.executable, "-c", source], check=False)
    assert result.returncode == 0, "token/theme layer pulled in PySide6"
