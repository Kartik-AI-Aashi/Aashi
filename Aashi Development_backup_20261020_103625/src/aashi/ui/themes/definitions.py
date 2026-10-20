"""Concrete theme definitions.

This module is the only place in Aashi where a literal colour value appears.
Everything else — widgets, stylesheets, painters — reads a resolved
:class:`Theme`.

Provenance is marked inline. ``spec §n`` cites the approved Aashi UI/UX Design
Specification. ``UI-02A decision`` marks a value the specification does not
state, chosen deliberately here and reported for approval; every such value was
verified against WCAG 2.2 contrast targets rather than picked by eye, and none
was produced by mathematically inverting its dark counterpart.

Nothing here imports Qt.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from aashi.ui.themes.mode import ColorScheme
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
)
from aashi.ui.tokens.elevation import Shadow, ambient_shadow

__all__ = [
    "ALL_THEMES",
    "DARK_THEME",
    "HIGH_CONTRAST_THEME",
    "LIGHT_THEME",
    "Theme",
    "theme_for",
]

_hex = Color.from_hex


@dataclass(frozen=True, slots=True)
class Theme:
    """A complete, resolved appearance.

    Attributes:
        name: Stable identifier, used in logs, tests and QSS comments.
        scheme: The colour scheme this theme satisfies.
        palette: Every colour token for this theme.
        shadow: The ambient shadow, cast only by the floating elevation tier.
        high_contrast: Whether this is a high-contrast variant. Widgets consult
            this to draw permanent outlines instead of relying on fills.
        allows_translucency: Whether glass, tints and scrims may be painted. The
            specification disables translucency entirely in high contrast.
    """

    name: str
    scheme: ColorScheme
    palette: ColorPalette
    shadow: Shadow
    high_contrast: bool = False
    allows_translucency: bool = True

    @property
    def is_dark(self) -> bool:
        """Whether this theme uses dark surfaces."""
        return self.scheme is ColorScheme.DARK


# ---------------------------------------------------------------------------
# Shared values
# ---------------------------------------------------------------------------

_ACCENT_GRADIENT: Final[LinearGradient] = LinearGradient(
    # spec §2.2 — violet to blue at 135 degrees, reserved for AI-state surfaces.
    angle_degrees=135.0,
    stops=(
        GradientStop(0.0, _hex("#7C6BFF")),
        GradientStop(1.0, _hex("#3FA9FF")),
    ),
)

_OVERLAY_SCRIM: Final[Color] = Color.from_rgba(11, 13, 18, 0.88)
"""spec §10.5 — the voice overlay scrim.

The specification states one scrim without qualifying it per theme, so both
themes use it. Flagged in the UI-02A report: a modal scrim this heavy may want a
lighter light-mode variant once modals exist.
"""


# ---------------------------------------------------------------------------
# Dark theme — the default. Every value below is stated by the specification.
# ---------------------------------------------------------------------------

_DARK_ACCENT: Final[Color] = _hex("#8B7CFA")  # spec §2.2

_DARK_PALETTE: Final[ColorPalette] = ColorPalette(
    surface=SurfaceColors(
        canvas=_hex("#0B0D12"),  # spec §2.1
        primary=_hex("#14161D"),  # spec §2.1
        elevated=_hex("#1B1E27"),  # spec §2.1
        nested=_hex("#22262F"),  # spec §2.1
        glass=Color.from_rgba(20, 22, 29, 0.72),  # spec §2.1
        glass_highlight=Color.from_rgba(255, 255, 255, 0.10),  # spec §2.1
        # UI-02C decision: neutral fill for the user's own chat bubble. The
        # specification's accent fill reads as a shout for compact messages, so
        # the bubble steps off the canvas (#0B0D12) and the elevated surface
        # (#1B1E27) instead of onto the accent. #F5F6FA on #2E333C measures
        # ~12.6:1, well past WCAG AA for body text.
        user_bubble=_hex("#2E333C"),
    ),
    text=TextColors(
        primary=_hex("#F5F6FA"),  # spec §2.4 — 18.00:1 on canvas
        secondary=_hex("#A6ACC0"),  # spec §2.4 — 8.59:1 on canvas
        tertiary=_hex("#5C6178"),  # spec §2.4 — 3.18:1, hints and disabled only
        inverse=_hex("#0B0D12"),  # spec §2.4 — 5.89:1 on the accent fill
    ),
    border=BorderColors(
        subtle=Color.from_rgba(255, 255, 255, 0.08),  # spec §2.1
        strong=Color.from_rgba(255, 255, 255, 0.14),  # spec §2.1
        # UI-02A decision: the focus ring reuses the accent. 5.89:1 on canvas,
        # 4.59:1 on the deepest nested surface — comfortably past the 3:1 that
        # WCAG 2.2 requires of a non-text indicator.
        focus=_DARK_ACCENT,
    ),
    accent=AccentColors(
        base=_DARK_ACCENT,  # spec §2.2 — 5.89:1 on canvas
        tint=_DARK_ACCENT.with_alpha(0.12),  # spec §2.2
        tint_hover=_DARK_ACCENT.with_alpha(0.20),  # spec §2.2
        # UI-02A decision: ink rather than white on the accent fill. Measured:
        # ink 5.89:1, white 3.30:1 — only the former passes AA for body text.
        on_accent=_hex("#0B0D12"),
        gradient=_ACCENT_GRADIENT,
    ),
    status=StatusColors(
        # spec §2.3. On dark surfaces each hue already exceeds AA as text
        # (9.6:1 to 10.2:1 on the primary surface), so base and text coincide.
        success=SemanticColor(
            base=_hex("#3DD68C"), text=_hex("#3DD68C"), tint=_hex("#3DD68C").with_alpha(0.12)
        ),
        warning=SemanticColor(
            base=_hex("#F5B944"), text=_hex("#F5B944"), tint=_hex("#F5B944").with_alpha(0.12)
        ),
        danger=SemanticColor(
            base=_hex("#F0555B"), text=_hex("#F0555B"), tint=_hex("#F0555B").with_alpha(0.12)
        ),
        information=SemanticColor(
            base=_hex("#4FA8FF"), text=_hex("#4FA8FF"), tint=_hex("#4FA8FF").with_alpha(0.12)
        ),
    ),
    scrim=_OVERLAY_SCRIM,
    shadow=Color.from_rgba(0, 0, 0, 0.40),  # spec §2.1
)

DARK_THEME: Final[Theme] = Theme(
    name="dark",
    scheme=ColorScheme.DARK,
    palette=_DARK_PALETTE,
    shadow=ambient_shadow(_DARK_PALETTE.shadow),
)


# ---------------------------------------------------------------------------
# Light theme
#
# The specification states eight light values (§2.5). The remainder are UI-02A
# decisions, designed for light surfaces rather than inverted from dark ones,
# and each verified against its target contrast ratio.
# ---------------------------------------------------------------------------

_LIGHT_ACCENT: Final[Color] = _hex("#6A57F0")  # spec §2.5

_LIGHT_PALETTE: Final[ColorPalette] = ColorPalette(
    surface=SurfaceColors(
        canvas=_hex("#F7F8FB"),  # spec §2.5
        primary=_hex("#FFFFFF"),  # spec §2.5
        elevated=_hex("#FCFCFE"),  # spec §2.5
        # UI-02A decision: light mode inverts the *direction* of depth. Dark
        # mode lifts a nested surface towards the light; light mode recesses it,
        # because a surface brighter than white does not exist. A 1.12:1 step
        # from white reads as a well without becoming a second panel.
        nested=_hex("#F0F2F7"),
        glass=Color.from_rgba(255, 255, 255, 0.76),  # spec §2.5
        # UI-02A decision: a white top highlight is invisible on a white glass
        # surface, so light mode defines the same 1px inner line as a faint dark
        # hairline. The line's job is to define the edge, not to catch light.
        glass_highlight=Color.from_rgba(0, 0, 0, 0.06),
        # UI-02C decision: the light companion to the dark user bubble — a touch
        # darker than the canvas (#F7F8FB) so the message recedes into a well.
        # #14161D on #E9EBF0 exceeds 14:1, comfortably past AA.
        user_bubble=_hex("#E9EBF0"),
    ),
    text=TextColors(
        primary=_hex("#14161D"),  # spec §2.5 — 17.01:1 on canvas
        secondary=_hex("#5A6076"),  # spec §2.5 — 5.87:1 on canvas
        # UI-02A decision: 3.15:1 on canvas and 3.34:1 on white, so hints stay
        # legible. The specification states no light tertiary value.
        tertiary=_hex("#868CA2"),
        # UI-02A decision: white, not the dark theme's ink. Measured on the
        # light accent: white 4.96:1 (AA), ink 3.64:1 (fails AA for body text).
        # The dark theme's "inverse equals canvas" rule cannot carry over.
        inverse=_hex("#FFFFFF"),
    ),
    border=BorderColors(
        subtle=Color.from_rgba(0, 0, 0, 0.08),  # spec §2.5
        # UI-02A decision: the strong tier mirrors the dark theme's own
        # 0.08 -> 0.14 relationship, inverted in polarity only.
        strong=Color.from_rgba(0, 0, 0, 0.14),
        focus=_LIGHT_ACCENT,  # 4.96:1 on white, 4.43:1 on the nested surface
    ),
    accent=AccentColors(
        base=_LIGHT_ACCENT,  # spec §2.5 — 4.96:1 on white
        # UI-02A decision: the specification's 12% and 20% tint strengths,
        # applied to the light accent.
        tint=_LIGHT_ACCENT.with_alpha(0.12),
        tint_hover=_LIGHT_ACCENT.with_alpha(0.20),
        on_accent=_hex("#FFFFFF"),
        gradient=_ACCENT_GRADIENT,  # spec §2.5 — the Orb gradient is unchanged
    ),
    status=StatusColors(
        # UI-02A decision, and the most consequential one in this module. The
        # specification names only the accent as shifting in light mode, but the
        # dark semantic hues fail badly on white: #3DD68C measures 1.88:1 there,
        # unusable as text and short of the 3:1 a status bar or icon needs.
        # Section 12 commits Aashi to WCAG AA on every surface, so light mode
        # uses one intentionally darkened hue per role, serving as fill, icon and
        # text alike. Ratios below are against the white primary surface.
        success=SemanticColor(
            base=_hex("#0E7C4A"), text=_hex("#0E7C4A"), tint=_hex("#0E7C4A").with_alpha(0.12)
        ),  # 5.25:1
        warning=SemanticColor(
            base=_hex("#9A6600"), text=_hex("#9A6600"), tint=_hex("#9A6600").with_alpha(0.12)
        ),  # 4.91:1
        danger=SemanticColor(
            base=_hex("#C62F35"), text=_hex("#C62F35"), tint=_hex("#C62F35").with_alpha(0.12)
        ),  # 5.44:1
        information=SemanticColor(
            base=_hex("#0B6BC7"), text=_hex("#0B6BC7"), tint=_hex("#0B6BC7").with_alpha(0.12)
        ),  # 5.33:1
    ),
    scrim=_OVERLAY_SCRIM,
    # UI-02A decision: 0.12 rather than the dark theme's 0.40. A shadow that
    # dark on a near-white surface reads as dirt rather than depth.
    shadow=Color.from_rgba(0, 0, 0, 0.12),
)

LIGHT_THEME: Final[Theme] = Theme(
    name="light",
    scheme=ColorScheme.LIGHT,
    palette=_LIGHT_PALETTE,
    shadow=ambient_shadow(_LIGHT_PALETTE.shadow),
)


# ---------------------------------------------------------------------------
# High contrast
#
# spec §2.6 — pure black canvas, pure white text, a lifted accent, a solid
# border on every interactive element, and no translucency anywhere. Aashi does
# not offer this as a user-selectable mode; it is applied when Windows reports
# high-contrast mode is active.
# ---------------------------------------------------------------------------

_HC_BLACK: Final[Color] = _hex("#000000")
_HC_WHITE: Final[Color] = _hex("#FFFFFF")
_HC_ACCENT: Final[Color] = _hex("#B7ACFF")  # spec §2.6 — 10.36:1 on black


def _high_contrast_semantic(value: str) -> SemanticColor:
    """Build a status role for high contrast: no tint, no derived variants."""
    color = _hex(value)
    return SemanticColor(base=color, text=color, tint=_HC_BLACK)


_HIGH_CONTRAST_PALETTE: Final[ColorPalette] = ColorPalette(
    surface=SurfaceColors(
        # Layering is expressed by borders here, not by surface colour, so every
        # surface collapses onto the canvas.
        canvas=_HC_BLACK,
        primary=_HC_BLACK,
        elevated=_HC_BLACK,
        nested=_HC_BLACK,
        glass=_HC_BLACK,
        glass_highlight=_HC_WHITE,
        # High contrast collapses every surface onto the canvas; the bubble is
        # told apart by the permanent outline the component draws in this mode,
        # so its fill collapses too.
        user_bubble=_HC_BLACK,
    ),
    text=TextColors(
        primary=_HC_WHITE,  # 21.00:1
        # Dimmed text is a contrast reduction by definition, so the secondary
        # and tertiary roles collapse onto the primary colour. Hierarchy is
        # carried by size and weight instead.
        secondary=_HC_WHITE,
        tertiary=_HC_WHITE,
        inverse=_HC_BLACK,
    ),
    border=BorderColors(subtle=_HC_WHITE, strong=_HC_WHITE, focus=_HC_ACCENT),
    accent=AccentColors(
        base=_HC_ACCENT,
        # Translucent washes are disabled; selection is shown with a border and
        # the accent colour, so the tints collapse onto the canvas.
        tint=_HC_BLACK,
        tint_hover=_HC_BLACK,
        on_accent=_HC_BLACK,  # 10.36:1 on the accent
        # Flattened: a gradient cannot guarantee contrast along its whole length.
        gradient=LinearGradient(
            angle_degrees=135.0,
            stops=(GradientStop(0.0, _HC_ACCENT), GradientStop(1.0, _HC_ACCENT)),
        ),
    ),
    status=StatusColors(
        success=_high_contrast_semantic("#3DD68C"),
        warning=_high_contrast_semantic("#F5B944"),
        danger=_high_contrast_semantic("#F0555B"),
        information=_high_contrast_semantic("#4FA8FF"),
    ),
    scrim=_HC_BLACK,
    shadow=_HC_BLACK.with_alpha(0.0),  # No shadows; depth comes from borders.
)

HIGH_CONTRAST_THEME: Final[Theme] = Theme(
    name="high-contrast",
    scheme=ColorScheme.DARK,
    palette=_HIGH_CONTRAST_PALETTE,
    shadow=ambient_shadow(_HIGH_CONTRAST_PALETTE.shadow),
    high_contrast=True,
    allows_translucency=False,
)


_BY_SCHEME: Final[dict[ColorScheme, Theme]] = {
    ColorScheme.DARK: DARK_THEME,
    ColorScheme.LIGHT: LIGHT_THEME,
}

ALL_THEMES: Final[Mapping[str, Theme]] = MappingProxyType(
    {theme.name: theme for theme in (DARK_THEME, LIGHT_THEME, HIGH_CONTRAST_THEME)}
)
"""Every defined theme, keyed by :attr:`Theme.name`."""


def theme_for(scheme: ColorScheme, *, high_contrast: bool = False) -> Theme:
    """Return the theme to display.

    Args:
        scheme: The resolved colour scheme.
        high_contrast: Whether the operating system reports high-contrast mode.
            When true it overrides ``scheme`` entirely: high contrast is an
            accessibility requirement, not a stylistic preference.

    Returns:
        The matching theme.
    """
    if high_contrast:
        return HIGH_CONTRAST_THEME
    return _BY_SCHEME[scheme]
