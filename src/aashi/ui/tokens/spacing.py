"""Spacing and layout-dimension tokens.

Aashi uses a base-8 spacing scale with a single half-step at 4px. Every margin,
padding and gap in the interface comes from :class:`Space`; a widget that needs
"just a bit more room" picks the next step rather than inventing a value.

Token names follow the specification's ``space-<n>`` convention, where 100 is
the 8px base unit. The numeric suffix therefore describes the *ratio* to the
base unit, which keeps the naming stable if a density mode is added later.

Nothing here imports Qt.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Final

__all__ = [
    "LAYOUT",
    "SPACING",
    "LayoutDimensions",
    "SemanticSpacing",
    "Space",
]


class Space(IntEnum):
    """The spacing scale, in logical pixels.

    Attributes:
        SPACE_050: 4px. Half step, for tight icon-to-label pairings only.
        SPACE_100: 8px. Base unit.
        SPACE_150: 12px. Vertical padding inside controls.
        SPACE_200: 16px. Horizontal padding inside controls.
        SPACE_300: 24px. Padding inside cards and panels.
        SPACE_400: 32px. Gap between sections of a view.
        SPACE_600: 48px. Page gutters at full width.
        SPACE_800: 64px. Largest sanctioned gap.
    """

    SPACE_050 = 4
    SPACE_100 = 8
    SPACE_150 = 12
    SPACE_200 = 16
    SPACE_300 = 24
    SPACE_400 = 32
    SPACE_600 = 48
    SPACE_800 = 64


@dataclass(frozen=True, slots=True)
class SemanticSpacing:
    """Named spacing decisions, so widgets express intent rather than numbers.

    Attributes:
        control_padding_vertical: Vertical padding inside a standard control.
        control_padding_horizontal: Horizontal padding inside a standard control.
        card_padding: Padding inside cards and panels.
        section_gap: Vertical gap between sections of a view.
        gutter: Page gutter at full width.
        gutter_compact: Page gutter below :attr:`gutter_breakpoint_px`.
        gutter_breakpoint_px: Window width at which gutters shrink.
        inline_gap: Gap between an icon and its adjacent label.
        stack_gap: Default gap between stacked sibling elements.
    """

    control_padding_vertical: int
    control_padding_horizontal: int
    card_padding: int
    section_gap: int
    gutter: int
    gutter_compact: int
    gutter_breakpoint_px: int
    inline_gap: int
    stack_gap: int

    def gutter_for_width(self, window_width_px: int) -> int:
        """Return the gutter appropriate to a window of ``window_width_px``."""
        if window_width_px < self.gutter_breakpoint_px:
            return self.gutter_compact
        return self.gutter


SPACING: Final[SemanticSpacing] = SemanticSpacing(
    control_padding_vertical=Space.SPACE_150,
    control_padding_horizontal=Space.SPACE_200,
    card_padding=Space.SPACE_300,
    section_gap=Space.SPACE_400,
    gutter=Space.SPACE_600,
    gutter_compact=Space.SPACE_300,
    gutter_breakpoint_px=1100,
    inline_gap=Space.SPACE_100,
    stack_gap=Space.SPACE_150,
)
"""The semantic spacing decisions taken by the approved specification."""


@dataclass(frozen=True, slots=True)
class LayoutDimensions:
    """Fixed structural widths, in logical pixels.

    These are chrome dimensions rather than spacing, but they belong with the
    spacing scale so that no widget hardcodes a panel width.

    Attributes:
        nav_rail_collapsed: Icon-only navigation rail.
        nav_rail_expanded: Navigation rail showing labels.
        master_list: Master column of a master/detail view.
        drawer: Slide-in drawer.
        context_panel: Right-hand contextual panel.
        content_reading: Content column optimised for reading.
        content_form: Content column optimised for forms.
    """

    nav_rail_collapsed: int
    nav_rail_expanded: int
    master_list: int
    drawer: int
    context_panel: int
    content_reading: int
    content_form: int


LAYOUT: Final[LayoutDimensions] = LayoutDimensions(
    nav_rail_collapsed=72,
    nav_rail_expanded=240,
    master_list=280,
    drawer=400,
    context_panel=320,
    content_reading=720,
    content_form=640,
)
"""Structural widths taken from the approved specification."""
