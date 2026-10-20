"""Reduced-motion preference detection and resolution.

Aashi honours the operating system's animation preference by default, and lets
that be overridden explicitly. The three-state :class:`MotionPreference` keeps
"follow the system" distinct from "the system currently says reduced", which is
the same distinction :class:`~aashi.ui.themes.mode.ThemeMode` draws for colour.

What a reduced-motion preference *means* for a given animation is decided by
:func:`aashi.ui.tokens.motion.resolve_duration`, not here. This module only
answers whether the preference is active.

Nothing here imports Qt. Detection is Windows-specific and degrades to "full
motion" on every other platform and on any failure — a wrong answer must not
prevent the application from starting.
"""

from __future__ import annotations

import logging
import sys
from enum import StrEnum
from typing import Final

__all__ = ["MotionPreference", "detect_system_reduced_motion"]

_logger = logging.getLogger(__name__)

_SPI_GET_CLIENT_AREA_ANIMATION: Final[int] = 0x1042
"""``SPI_GETCLIENTAREAANIMATION``. Reports whether Windows animates UI elements.

Windows exposes this under Settings > Accessibility > Visual effects >
Animation effects. It is the closest equivalent to the web's
``prefers-reduced-motion`` and is what other Windows applications honour.
"""


class MotionPreference(StrEnum):
    """How much animation the interface should use.

    Attributes:
        SYSTEM: Follow the operating system. The default.
        FULL: Always animate, whatever the operating system says.
        REDUCED: Always minimise motion, whatever the operating system says.
    """

    SYSTEM = "system"
    FULL = "full"
    REDUCED = "reduced"

    @classmethod
    def parse(cls, value: str) -> MotionPreference:
        """Parse a case-insensitive preference name.

        Raises:
            ValueError: If ``value`` names no known preference.
        """
        try:
            return cls(value.strip().lower())
        except ValueError:
            valid = ", ".join(item.value for item in cls)
            raise ValueError(
                f"Unknown motion preference {value!r}. Expected one of: {valid}"
            ) from None

    def resolve(self, *, system_reduced: bool) -> bool:
        """Resolve this preference to a concrete answer.

        Args:
            system_reduced: Whether the operating system currently asks for
                reduced motion. Ignored unless this preference is :attr:`SYSTEM`.

        Returns:
            True when motion should be minimised.
        """
        if self is MotionPreference.FULL:
            return False
        if self is MotionPreference.REDUCED:
            return True
        return system_reduced


def detect_system_reduced_motion() -> bool:
    """Return whether the operating system currently asks for reduced motion.

    On Windows this reads ``SPI_GETCLIENTAREAANIMATION``. Everywhere else, and
    whenever the call fails, the answer is False: Aashi animates normally rather
    than guessing that the user wants motion suppressed.

    Returns:
        True when the operating system reports that UI animation is disabled.
    """
    if sys.platform != "win32":
        return False

    try:
        import ctypes
        from ctypes import wintypes

        enabled = wintypes.BOOL()
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        succeeded = user32.SystemParametersInfoW(
            _SPI_GET_CLIENT_AREA_ANIMATION,
            0,
            ctypes.byref(enabled),
            0,
        )
    except (OSError, AttributeError, ValueError) as exc:
        _logger.debug("Could not read the system animation preference: %s", exc)
        return False

    if not succeeded:
        _logger.debug(
            "SystemParametersInfoW(SPI_GETCLIENTAREAANIMATION) failed; assuming full motion."
        )
        return False

    # The API reports whether animations are *enabled*, so reduced motion is the
    # negation of what it returns.
    return not bool(enabled.value)
