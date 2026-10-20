"""Themes and the theme engine.

Holds the concrete appearances Aashi ships and the runtime that resolves design
tokens into an applied one:

- :mod:`~aashi.ui.themes.mode` — the user's choice and the resolved scheme.
- :mod:`~aashi.ui.themes.definitions` — the dark, light and high-contrast themes.
  The only place in Aashi where a literal colour value appears.
- :mod:`~aashi.ui.themes.qss` — token substitution for Qt stylesheets.
- :mod:`~aashi.ui.themes.system` — operating-system appearance detection.
- :mod:`~aashi.ui.themes.qt_adapters` — token to Qt type conversions.
- :mod:`~aashi.ui.themes.manager` — :class:`~aashi.ui.themes.manager.ThemeManager`.

This ``__init__`` re-exports only the Qt-free half. ``ThemeManager`` and the Qt
adapters are imported from their own modules on purpose:

    from aashi.ui.themes.manager import ThemeManager

Re-exporting them here would make ``import aashi.ui.themes.definitions`` load
PySide6 as a side effect, which would in turn make theme values impossible to
test, document or diff without a GUI toolkit present. Tests enforce the split.
"""

from __future__ import annotations

from aashi.ui.themes.definitions import (
    ALL_THEMES,
    DARK_THEME,
    HIGH_CONTRAST_THEME,
    LIGHT_THEME,
    Theme,
    theme_for,
)
from aashi.ui.themes.mode import ColorScheme, ThemeMode
from aashi.ui.themes.qss import (
    QssTemplateError,
    build_base_stylesheet,
    qss_variables,
    render_qss,
)
from aashi.ui.themes.system import (
    DEFAULT_SYSTEM_PREFERENCES,
    SystemPreferenceReader,
    SystemPreferences,
    read_system_preferences,
)

__all__ = [
    "ALL_THEMES",
    "DARK_THEME",
    "DEFAULT_SYSTEM_PREFERENCES",
    "HIGH_CONTRAST_THEME",
    "LIGHT_THEME",
    "ColorScheme",
    "QssTemplateError",
    "SystemPreferenceReader",
    "SystemPreferences",
    "Theme",
    "ThemeMode",
    "build_base_stylesheet",
    "qss_variables",
    "read_system_preferences",
    "render_qss",
    "theme_for",
]
