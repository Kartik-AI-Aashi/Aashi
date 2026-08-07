"""Design tokens — the single source of truth for Aashi's visual values.

Every colour, font size, space, radius, border width, shadow, duration and
control height used anywhere in the interface originates here. Widgets read
tokens; they never hardcode a visual constant. If a value is not in this package
it is not a sanctioned value.

The package is split by kind:

- :mod:`~aashi.ui.tokens.color` — colour value types and the shape of a palette.
- :mod:`~aashi.ui.tokens.typography` — the six text roles and font stacks.
- :mod:`~aashi.ui.tokens.spacing` — the base-8 space scale and layout widths.
- :mod:`~aashi.ui.tokens.radius` — corner radii.
- :mod:`~aashi.ui.tokens.borders` — stroke widths.
- :mod:`~aashi.ui.tokens.elevation` — depth tiers, shadow geometry and blur.
- :mod:`~aashi.ui.tokens.motion` — durations, easing and reduced-motion roles.
- :mod:`~aashi.ui.tokens.controls` — control, icon and Orb sizes.

Concrete *colour values* are deliberately absent: they vary per theme and live
in :mod:`aashi.ui.themes.definitions`. Everything in this package is
theme-independent.

This package must remain free of Qt imports. Tokens are plain data so they can
be tested, diffed and documented without a running ``QApplication``; conversion
to Qt types happens in :mod:`aashi.ui.themes.qt_adapters`. A test enforces this.
"""

from __future__ import annotations

from aashi.ui.tokens.borders import (
    FOCUS_RING_MIN_CONTRAST,
    HIGH_CONTRAST_BORDER_WIDTH,
    BorderWidth,
)
from aashi.ui.tokens.color import (
    AccentColors,
    BorderColors,
    Color,
    ColorPalette,
    GradientStop,
    LinearGradient,
    SemanticColor,
    StatusColors,
    SurfaceColors,
    TextColors,
    contrast_ratio,
    relative_luminance,
)
from aashi.ui.tokens.controls import (
    HIT_TARGET_MIN_PX,
    HIT_TARGET_PREFERRED_PX,
    TABLE_ROW_HEIGHT_PX,
    TOAST_MAX_STACKED,
    ControlHeight,
    IconSize,
    OrbSize,
)
from aashi.ui.tokens.elevation import (
    AMBIENT_SHADOW_BLUR_PX,
    AMBIENT_SHADOW_OFFSET_X_PX,
    AMBIENT_SHADOW_OFFSET_Y_PX,
    GLASS_BLUR_PX,
    OVERLAY_BLUR_PX,
    Elevation,
    Shadow,
    ambient_shadow,
)
from aashi.ui.tokens.motion import (
    EASING_ENTRANCE,
    EASING_EXIT,
    LOADING_INDICATOR_DELAY_MS,
    ORB_IDLE_CYCLE_MAX_MS,
    ORB_IDLE_CYCLE_MIN_MS,
    ORB_THINKING_CYCLE_MS,
    TOAST_VISIBLE_MS,
    TOOLTIP_DELAY_MS,
    Duration,
    Easing,
    MotionRole,
    resolve_duration,
    resolve_easing,
)
from aashi.ui.tokens.radius import Radius
from aashi.ui.tokens.spacing import (
    LAYOUT,
    SPACING,
    LayoutDimensions,
    SemanticSpacing,
    Space,
)
from aashi.ui.tokens.typography import (
    ALLOW_ITALICS,
    FONT_FAMILY_CODE,
    FONT_FAMILY_UI,
    LIST_ITEM_GAP_PX,
    MEASURE_DESCRIPTION_PX,
    MEASURE_PROSE_PX,
    PARAGRAPH_GAP_PX,
    TYPOGRAPHY,
    USE_TABULAR_FIGURES,
    FontWeight,
    TextRole,
    TextStyle,
    code_style,
    style_for,
)

__all__ = [
    # colour
    "AccentColors",
    "BorderColors",
    "Color",
    "ColorPalette",
    "GradientStop",
    "LinearGradient",
    "SemanticColor",
    "StatusColors",
    "SurfaceColors",
    "TextColors",
    "contrast_ratio",
    "relative_luminance",
    # typography
    "ALLOW_ITALICS",
    "FONT_FAMILY_CODE",
    "FONT_FAMILY_UI",
    "LIST_ITEM_GAP_PX",
    "MEASURE_DESCRIPTION_PX",
    "MEASURE_PROSE_PX",
    "PARAGRAPH_GAP_PX",
    "TYPOGRAPHY",
    "USE_TABULAR_FIGURES",
    "FontWeight",
    "TextRole",
    "TextStyle",
    "code_style",
    "style_for",
    # spacing and layout
    "LAYOUT",
    "SPACING",
    "LayoutDimensions",
    "SemanticSpacing",
    "Space",
    # radius and borders
    "FOCUS_RING_MIN_CONTRAST",
    "HIGH_CONTRAST_BORDER_WIDTH",
    "BorderWidth",
    "Radius",
    # elevation
    "AMBIENT_SHADOW_BLUR_PX",
    "AMBIENT_SHADOW_OFFSET_X_PX",
    "AMBIENT_SHADOW_OFFSET_Y_PX",
    "GLASS_BLUR_PX",
    "OVERLAY_BLUR_PX",
    "Elevation",
    "Shadow",
    "ambient_shadow",
    # motion
    "EASING_ENTRANCE",
    "EASING_EXIT",
    "LOADING_INDICATOR_DELAY_MS",
    "ORB_IDLE_CYCLE_MAX_MS",
    "ORB_IDLE_CYCLE_MIN_MS",
    "ORB_THINKING_CYCLE_MS",
    "TOAST_VISIBLE_MS",
    "TOOLTIP_DELAY_MS",
    "Duration",
    "Easing",
    "MotionRole",
    "resolve_duration",
    "resolve_easing",
    # controls
    "HIT_TARGET_MIN_PX",
    "HIT_TARGET_PREFERRED_PX",
    "TABLE_ROW_HEIGHT_PX",
    "TOAST_MAX_STACKED",
    "ControlHeight",
    "IconSize",
    "OrbSize",
]
