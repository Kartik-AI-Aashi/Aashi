"""Border and outline tokens.

Border *colours* vary per theme and therefore live in the theme's
:class:`~aashi.ui.tokens.color.BorderColors`. This module owns the widths, which
do not vary.

Nothing here imports Qt.
"""

from __future__ import annotations

from enum import IntEnum
from typing import Final

__all__ = ["FOCUS_RING_MIN_CONTRAST", "HIGH_CONTRAST_BORDER_WIDTH", "BorderWidth"]


class BorderWidth(IntEnum):
    """Stroke widths, in logical pixels.

    Attributes:
        HAIRLINE: 1px. Separators, container outlines and glass highlights.
        FOCUS_RING: 2px. Keyboard focus indicator.
        INDICATOR: 3px. Selection bars and unread markers, such as the active
            navigation rail item and the leading edge of an unread notification.
    """

    HAIRLINE = 1
    FOCUS_RING = 2
    INDICATOR = 3


FOCUS_RING_MIN_CONTRAST: Final[float] = 3.0
"""Minimum contrast the focus ring must reach against its adjacent surface.

WCAG 2.2 requires 3:1 for non-text interface components. Tests assert this
against every theme rather than trusting the palette by eye.
"""

HIGH_CONTRAST_BORDER_WIDTH: Final[int] = BorderWidth.HAIRLINE
"""Width of the solid border every interactive element gains in high contrast.

In high-contrast mode the specification replaces fills and translucency with
explicit outlines, so the border is always drawn rather than only on hover.
"""
