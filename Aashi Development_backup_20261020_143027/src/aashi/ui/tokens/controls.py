"""Control-size tokens.

Sizes for interactive elements, icons and hit targets. These exist now, ahead of
the components that will use them, precisely so that the component library never
has a reason to hardcode a height.

Nothing here imports Qt.
"""

from __future__ import annotations

from enum import IntEnum
from typing import Final

__all__ = [
    "HIT_TARGET_MIN_PX",
    "HIT_TARGET_PREFERRED_PX",
    "TABLE_ROW_HEIGHT_PX",
    "TOAST_MAX_STACKED",
    "ControlHeight",
    "IconSize",
    "OrbSize",
]


class ControlHeight(IntEnum):
    """Heights of interactive controls, in logical pixels.

    Attributes:
        COMPACT: 32px. Dense toolbars and inline controls.
        DEFAULT: 40px. Buttons, inputs and selects everywhere else.
        LARGE: 48px. Primary calls to action and touch-friendly contexts.
    """

    COMPACT = 32
    DEFAULT = 40
    LARGE = 48


class IconSize(IntEnum):
    """Icon box sizes, in logical pixels.

    Attributes:
        SMALL: 16px. Inline with caption and micro text.
        MEDIUM: 20px. Inline with body text and inside standard controls.
        LARGE: 24px. Navigation and standalone actions.
    """

    SMALL = 16
    MEDIUM = 20
    LARGE = 24


class OrbSize(IntEnum):
    """Rendered diameters of the Aashi Orb, in logical pixels.

    The Orb itself belongs to a later module; only its size scale is a token, so
    that the module which builds it inherits the specification's values instead
    of restating them.

    Attributes:
        MICRO: 16px. Inline status dot.
        SMALL: 24px. Compact list and toolbar presence.
        MEDIUM: 48px. Docked companion.
        LARGE: 96px. Panel-level presence.
        XLARGE: 120px. Voice overlay.
        HERO: 200px. Splash and onboarding.
    """

    MICRO = 16
    SMALL = 24
    MEDIUM = 48
    LARGE = 96
    XLARGE = 120
    HERO = 200


TABLE_ROW_HEIGHT_PX: Final[int] = 48
"""Height of a row in a data table."""

HIT_TARGET_MIN_PX: Final[int] = 24
"""Absolute minimum interactive area, per WCAG 2.2 target size (minimum)."""

HIT_TARGET_PREFERRED_PX: Final[int] = 40
"""Preferred interactive area. Matches :attr:`ControlHeight.DEFAULT`."""

TOAST_MAX_STACKED: Final[int] = 3
"""Maximum toasts shown at once; further toasts queue rather than stack."""
