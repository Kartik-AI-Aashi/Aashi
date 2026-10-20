"""Operating-system appearance detection.

Reads the three preferences Aashi honours: the colour scheme, high-contrast mode
and reduced motion. The result is bundled into an immutable
:class:`SystemPreferences` snapshot so that a caller sees one coherent picture
rather than three values read at three different moments.

Detection is Windows-specific and deliberately forgiving. Every failure path
falls back to a documented default rather than raising: an unreadable registry
key must never stop Aashi from starting, and the user can always choose an
explicit theme mode instead.

Nothing here imports Qt. When Qt is running, :class:`aashi.ui.themes.manager
.ThemeManager` prefers Qt's own ``QStyleHints.colorScheme()`` — which is more
accurate and, on Qt 6.5+, also emits a change signal — and uses this module as
the fallback and as the sole source for high contrast and reduced motion.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from aashi.ui.accessibility.reduced_motion import detect_system_reduced_motion
from aashi.ui.themes.mode import ColorScheme

__all__ = [
    "DEFAULT_SYSTEM_PREFERENCES",
    "SystemPreferenceReader",
    "SystemPreferences",
    "detect_system_color_scheme",
    "detect_system_high_contrast",
    "read_system_preferences",
]

_logger = logging.getLogger(__name__)

_PERSONALIZE_KEY: Final[str] = (
    r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
)
_APPS_USE_LIGHT_THEME: Final[str] = "AppsUseLightTheme"
"""Windows stores the app colour scheme here: 1 means light, 0 means dark."""

_SPI_GET_HIGH_CONTRAST: Final[int] = 0x0042
_HCF_HIGH_CONTRAST_ON: Final[int] = 0x00000001


@dataclass(frozen=True, slots=True)
class SystemPreferences:
    """A coherent snapshot of the operating system's appearance preferences.

    Attributes:
        color_scheme: The scheme the operating system currently prefers.
        high_contrast: Whether high-contrast mode is active. When true it
            overrides the colour scheme entirely.
        reduced_motion: Whether the operating system asks for reduced motion.
    """

    color_scheme: ColorScheme
    high_contrast: bool
    reduced_motion: bool


DEFAULT_SYSTEM_PREFERENCES: Final[SystemPreferences] = SystemPreferences(
    # Aashi is designed dark-first, so an unknown preference resolves to dark
    # rather than to light.
    color_scheme=ColorScheme.DARK,
    high_contrast=False,
    reduced_motion=False,
)
"""The snapshot used when the operating system cannot be queried."""

SystemPreferenceReader = Callable[[], SystemPreferences]
"""Callable returning a preferences snapshot.

Injected wherever detection needs to be replaced, so that tests never depend on
the machine running them.
"""


def detect_system_color_scheme() -> ColorScheme:
    """Return the colour scheme Windows currently prefers for applications.

    Returns:
        The detected scheme, or :attr:`ColorScheme.DARK` on any other platform
        and on any failure.
    """
    if sys.platform != "win32":
        return DEFAULT_SYSTEM_PREFERENCES.color_scheme

    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _PERSONALIZE_KEY) as key:
            value, value_type = winreg.QueryValueEx(key, _APPS_USE_LIGHT_THEME)
    except (OSError, ImportError) as exc:
        _logger.debug("Could not read the system colour scheme: %s", exc)
        return DEFAULT_SYSTEM_PREFERENCES.color_scheme

    if value_type != winreg.REG_DWORD or not isinstance(value, int):
        _logger.debug("%s held an unexpected value: %r", _APPS_USE_LIGHT_THEME, value)
        return DEFAULT_SYSTEM_PREFERENCES.color_scheme

    return ColorScheme.LIGHT if value else ColorScheme.DARK


def detect_system_high_contrast() -> bool:
    """Return whether Windows high-contrast mode is active.

    Returns:
        True when high contrast is on. False on any other platform and on any
        failure — falsely claiming high contrast would degrade the interface for
        everyone else.
    """
    if sys.platform != "win32":
        return False

    try:
        import ctypes
        from ctypes import wintypes

        class _HighContrast(ctypes.Structure):
            _fields_ = (
                ("cbSize", wintypes.UINT),
                ("dwFlags", wintypes.DWORD),
                ("lpszDefaultScheme", wintypes.LPWSTR),
            )

        info = _HighContrast()
        info.cbSize = ctypes.sizeof(_HighContrast)
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        succeeded = user32.SystemParametersInfoW(
            _SPI_GET_HIGH_CONTRAST,
            info.cbSize,
            ctypes.byref(info),
            0,
        )
    except (OSError, AttributeError, ValueError) as exc:
        _logger.debug("Could not read the system high-contrast preference: %s", exc)
        return False

    if not succeeded:
        _logger.debug("SystemParametersInfoW(SPI_GETHIGHCONTRAST) failed; assuming off.")
        return False

    return bool(info.dwFlags & _HCF_HIGH_CONTRAST_ON)


def read_system_preferences() -> SystemPreferences:
    """Read every appearance preference in one pass.

    Returns:
        An immutable snapshot. Values that cannot be read take their documented
        default from :data:`DEFAULT_SYSTEM_PREFERENCES`.
    """
    preferences = SystemPreferences(
        color_scheme=detect_system_color_scheme(),
        high_contrast=detect_system_high_contrast(),
        reduced_motion=detect_system_reduced_motion(),
    )
    _logger.debug("System appearance preferences: %s", preferences)
    return preferences
