"""Elevation, shadow and blur tokens.

Aashi expresses depth mostly through surface *layering* rather than shadow. The
specification sanctions exactly one ambient shadow, applied only to floating
tiers; everything below that tier is separated by surface colour and a hairline
border.

The shadow *colour* varies per theme, so :class:`Shadow` instances are built in
:mod:`aashi.ui.themes.definitions`. This module owns the geometry, which does
not vary, plus the blur radii used by translucent surfaces.

Nothing here imports Qt.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Final

from aashi.ui.tokens.color import Color

__all__ = [
    "AMBIENT_SHADOW_BLUR_PX",
    "AMBIENT_SHADOW_OFFSET_X_PX",
    "AMBIENT_SHADOW_OFFSET_Y_PX",
    "GLASS_BLUR_PX",
    "OVERLAY_BLUR_PX",
    "Elevation",
    "Shadow",
    "ambient_shadow",
]


class Elevation(IntEnum):
    """Depth tiers.

    Attributes:
        FLAT: Sits directly on the canvas. No shadow.
        RAISED: Panels and cards. Separated by surface colour and a hairline,
            never by a shadow.
        FLOATING: Popovers, modals, toasts and floating AI surfaces. The only
            tier permitted to cast the ambient shadow.
    """

    FLAT = 0
    RAISED = 1
    FLOATING = 2

    @property
    def casts_shadow(self) -> bool:
        """Whether this tier draws the ambient shadow."""
        return self is Elevation.FLOATING


AMBIENT_SHADOW_OFFSET_X_PX: Final[int] = 0
AMBIENT_SHADOW_OFFSET_Y_PX: Final[int] = 8
AMBIENT_SHADOW_BLUR_PX: Final[int] = 24
"""Geometry of the single sanctioned ambient shadow: ``0 8px 24px``."""

GLASS_BLUR_PX: Final[int] = 24
"""Backdrop blur behind a translucent glass surface."""

OVERLAY_BLUR_PX: Final[int] = 32
"""Backdrop blur behind a full-screen overlay, such as the voice overlay."""


@dataclass(frozen=True, slots=True)
class Shadow:
    """A single drop shadow.

    Attributes:
        offset_x: Horizontal offset in logical pixels.
        offset_y: Vertical offset in logical pixels.
        blur_px: Blur radius in logical pixels.
        color: Shadow colour, normally translucent black.
    """

    offset_x: int
    offset_y: int
    blur_px: int
    color: Color

    @property
    def css(self) -> str:
        """CSS ``box-shadow`` notation.

        Qt stylesheets do not support ``box-shadow``; shadows are painted with
        ``QGraphicsDropShadowEffect`` instead. This exists for documentation and
        for the development preview, so the value is never restated by hand.
        """
        return f"{self.offset_x}px {self.offset_y}px {self.blur_px}px {self.color.css}"


def ambient_shadow(color: Color) -> Shadow:
    """Build the ambient shadow for a theme from its shadow colour."""
    return Shadow(
        offset_x=AMBIENT_SHADOW_OFFSET_X_PX,
        offset_y=AMBIENT_SHADOW_OFFSET_Y_PX,
        blur_px=AMBIENT_SHADOW_BLUR_PX,
        color=color,
    )
