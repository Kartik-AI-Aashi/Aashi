"""Verify the UI-02A design-token layer.

Tokens are pure data and deliberately Qt-free. These tests check the colour
primitives and WCAG helpers, the type scale, the spacing scale, the motion
tables and the control sizes — the values every later widget will read.
"""

from __future__ import annotations

import pytest

from aashi.ui.tokens.borders import BorderWidth
from aashi.ui.tokens.color import Color, contrast_ratio, relative_luminance
from aashi.ui.tokens.controls import (
    HIT_TARGET_MIN_PX,
    HIT_TARGET_PREFERRED_PX,
    ControlHeight,
)
from aashi.ui.tokens.elevation import Elevation, ambient_shadow
from aashi.ui.tokens.motion import (
    EASING_ENTRANCE,
    EASING_EXIT,
    Duration,
    MotionRole,
    resolve_duration,
    resolve_easing,
)
from aashi.ui.tokens.radius import Radius
from aashi.ui.tokens.spacing import LAYOUT, SPACING, Space
from aashi.ui.tokens.typography import (
    FONT_FAMILY_CODE,
    TYPOGRAPHY,
    TextRole,
    code_style,
    style_for,
)


# ---------------------------------------------------------------------------
# Colour
# ---------------------------------------------------------------------------


def test_color_parses_hex_rgb() -> None:
    color = Color.from_hex("#3DD68C")
    assert color.rgb == (0x3D, 0xD6, 0x8C)
    assert color.is_opaque


def test_color_parses_hex_rgba() -> None:
    color = Color.from_hex("#FFFFFF14")
    assert color.rgb == (255, 255, 255)
    assert color.alpha_255 == 0x14


@pytest.mark.parametrize("value", ["#12345", "not-a-color"])
def test_color_rejects_invalid_hex(value: str) -> None:
    with pytest.raises(ValueError):
        Color.from_hex(value)


def test_color_css_keeps_alpha_for_translucent_colours() -> None:
    assert Color.from_rgba(20, 22, 29, 0.72).css == "rgba(20, 22, 29, 184)"
    assert Color.from_hex("#0B0D12").css == "#0b0d12"


def test_color_with_alpha_returns_an_unchanged_copy() -> None:
    base = Color.from_hex("#8B7CFA")
    faded = base.with_alpha(0.12)
    assert faded.alpha == 0.12
    assert base.alpha == 1.0


def test_composite_over_flattens_a_translucent_foreground() -> None:
    flattened = Color.from_rgba(255, 255, 255, 0.08).composite_over(
        Color.from_hex("#0B0D12")
    )
    assert flattened.is_opaque


def test_composite_over_rejects_a_translucent_background() -> None:
    with pytest.raises(ValueError):
        Color.from_rgba(0, 0, 0, 0.5).composite_over(Color.from_rgba(0, 0, 0, 0.5))


def test_contrast_ratio_extremes() -> None:
    black = Color.from_hex("#000000")
    white = Color.from_hex("#FFFFFF")
    assert contrast_ratio(white, black) == pytest.approx(21.0)
    assert contrast_ratio(black, black) == pytest.approx(1.0)


def test_relative_luminance_rejects_translucent_colours() -> None:
    with pytest.raises(ValueError):
        relative_luminance(Color.from_rgba(0, 0, 0, 0.5))


# ---------------------------------------------------------------------------
# Typography
# ---------------------------------------------------------------------------


def test_typography_defines_exactly_six_roles() -> None:
    assert set(TYPOGRAPHY) == set(TextRole)


def test_style_for_returns_the_matching_style() -> None:
    assert style_for(TextRole.BODY).role is TextRole.BODY
    assert style_for(TextRole.BODY).size_px == 14


def test_micro_role_is_uppercase_and_tracked() -> None:
    micro = style_for(TextRole.MICRO)
    assert micro.uppercase is True
    assert micro.letter_spacing_em > 0


def test_code_style_swaps_only_the_family() -> None:
    body = style_for(TextRole.BODY)
    code = code_style(TextRole.BODY)
    assert code.family == FONT_FAMILY_CODE
    assert code.size_px == body.size_px
    assert code.line_height_px == body.line_height_px


# ---------------------------------------------------------------------------
# Spacing and layout
# ---------------------------------------------------------------------------


def test_spacing_scale_is_base_8_with_a_single_half_step() -> None:
    assert Space.SPACE_050.value == 4  # the half step
    assert Space.SPACE_100.value == 8  # the base unit
    values = [space.value for space in Space]
    assert values == sorted(values)
    # The numeric suffix is the ratio to the 8px base unit: value = 8 × ratio.
    for space in Space:
        ratio = int(space.name.removeprefix("SPACE_"))
        assert space.value == 8 * ratio // 100


def test_gutter_shrinks_below_the_breakpoint() -> None:
    assert SPACING.gutter_for_width(SPACING.gutter_breakpoint_px - 1) == SPACING.gutter_compact
    assert SPACING.gutter_for_width(SPACING.gutter_breakpoint_px) == SPACING.gutter


def test_layout_widths_are_all_positive() -> None:
    for field in (
        "nav_rail_collapsed",
        "nav_rail_expanded",
        "master_list",
        "drawer",
        "context_panel",
        "content_reading",
        "content_form",
    ):
        assert getattr(LAYOUT, field) > 0


# ---------------------------------------------------------------------------
# Motion
# ---------------------------------------------------------------------------


def test_spatial_motion_becomes_instant_when_reduced() -> None:
    assert resolve_duration(MotionRole.SPATIAL, reduced_motion=False) == Duration.SLOW
    assert resolve_duration(MotionRole.SPATIAL, reduced_motion=True) == Duration.INSTANT


def test_state_feedback_survives_reduced_motion() -> None:
    # Feedback carries information, so it must never be removed.
    assert resolve_duration(MotionRole.STATE_FEEDBACK, reduced_motion=True) == Duration.FAST


def test_continuous_motion_stops_when_reduced() -> None:
    assert resolve_duration(MotionRole.CONTINUOUS, reduced_motion=True) == Duration.INSTANT


def test_resolve_easing_selects_entrance_or_exit() -> None:
    assert resolve_easing(MotionRole.TRANSITION, entering=True) is EASING_ENTRANCE
    assert resolve_easing(MotionRole.TRANSITION, entering=False) is EASING_EXIT


# ---------------------------------------------------------------------------
# Radius, borders and controls
# ---------------------------------------------------------------------------


def test_radius_scale_is_ordered() -> None:
    values = [radius.value for radius in Radius]
    assert values == sorted(values)


def test_border_widths_are_ordered() -> None:
    values = [width.value for width in BorderWidth]
    assert values == sorted(values)


def test_control_heights_meet_the_hit_target_contract() -> None:
    assert ControlHeight.COMPACT.value >= HIT_TARGET_MIN_PX
    assert ControlHeight.DEFAULT.value == HIT_TARGET_PREFERRED_PX


def test_only_the_floating_tier_casts_a_shadow() -> None:
    assert Elevation.FLOATING.casts_shadow
    assert not Elevation.RAISED.casts_shadow
    assert not Elevation.FLAT.casts_shadow


def test_ambient_shadow_builds_the_sanctioned_geometry() -> None:
    shadow = ambient_shadow(Color.from_hex("#000000"))
    assert shadow.offset_x == 0
    assert shadow.offset_y == 8
    assert shadow.blur_px == 24
