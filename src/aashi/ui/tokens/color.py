"""Colour primitives for the Aashi design-token system.

This module defines the *vocabulary* of colour — the value types and the shape
of a palette — but deliberately holds no palette values of its own. Concrete
palettes vary per theme and therefore live in :mod:`aashi.ui.themes.definitions`.

Nothing here may import Qt. Tokens are plain data so that they can be tested,
serialized and reasoned about without a running ``QApplication``; the Qt
adapters in :mod:`aashi.ui.themes.qt_adapters` convert them when needed.

The contrast helpers implement WCAG 2.2 relative luminance so that the ratios
promised by the approved UI/UX specification can be *verified by tests* rather
than assumed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

__all__ = [
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
]

CHANNEL_MAX: Final[int] = 255
"""Maximum value of an 8-bit colour channel."""

_HEX_LENGTH_RGB: Final[int] = 6
_HEX_LENGTH_RGBA: Final[int] = 8
_SRGB_LINEAR_THRESHOLD: Final[float] = 0.04045
_SRGB_LINEAR_DIVISOR: Final[float] = 12.92
_SRGB_GAMMA_OFFSET: Final[float] = 0.055
_SRGB_GAMMA_DIVISOR: Final[float] = 1.055
_SRGB_GAMMA_EXPONENT: Final[float] = 2.4
_LUMINANCE_RED_WEIGHT: Final[float] = 0.2126
_LUMINANCE_GREEN_WEIGHT: Final[float] = 0.7152
_LUMINANCE_BLUE_WEIGHT: Final[float] = 0.0722
_CONTRAST_OFFSET: Final[float] = 0.05


@dataclass(frozen=True, slots=True)
class Color:
    """An immutable sRGB colour with straight (non-premultiplied) alpha.

    Alpha is stored as a fraction so that specification values such as
    ``rgba(255, 255, 255, 0.08)`` survive round-tripping exactly. Conversion to
    the 0-255 integer alpha that Qt expects happens only at the boundary, via
    :attr:`alpha_255`.

    Attributes:
        red: Red channel, 0-255.
        green: Green channel, 0-255.
        blue: Blue channel, 0-255.
        alpha: Opacity fraction, 0.0 (transparent) to 1.0 (opaque).
    """

    red: int
    green: int
    blue: int
    alpha: float = 1.0

    def __post_init__(self) -> None:
        for name in ("red", "green", "blue"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError(f"Color.{name} must be an int, got {value!r}")
            if not 0 <= value <= CHANNEL_MAX:
                raise ValueError(f"Color.{name} must be 0-{CHANNEL_MAX}, got {value}")
        if not 0.0 <= self.alpha <= 1.0:
            raise ValueError(f"Color.alpha must be 0.0-1.0, got {self.alpha}")

    # -- construction -------------------------------------------------------

    @classmethod
    def from_hex(cls, value: str) -> Color:
        """Build a colour from ``#RRGGBB`` or ``#RRGGBBAA``.

        Args:
            value: Hex string, with or without the leading ``#``.

        Returns:
            The parsed colour.

        Raises:
            ValueError: If the string is not a 6- or 8-digit hex colour.
        """
        digits = value.strip().lstrip("#")
        if len(digits) not in (_HEX_LENGTH_RGB, _HEX_LENGTH_RGBA):
            raise ValueError(f"Expected #RRGGBB or #RRGGBBAA, got {value!r}")
        try:
            channels = [int(digits[i : i + 2], 16) for i in range(0, len(digits), 2)]
        except ValueError as exc:
            raise ValueError(f"Not a hex colour: {value!r}") from exc
        red, green, blue = channels[:3]
        alpha = channels[3] / CHANNEL_MAX if len(channels) == 4 else 1.0
        return cls(red, green, blue, alpha)

    @classmethod
    def from_rgba(cls, red: int, green: int, blue: int, alpha: float) -> Color:
        """Build a translucent colour, mirroring CSS ``rgba()`` notation."""
        return cls(red, green, blue, alpha)

    def with_alpha(self, alpha: float) -> Color:
        """Return a copy of this colour at a different opacity."""
        return Color(self.red, self.green, self.blue, alpha)

    # -- inspection ---------------------------------------------------------

    @property
    def is_opaque(self) -> bool:
        """Whether the colour is fully opaque."""
        return self.alpha >= 1.0

    @property
    def alpha_255(self) -> int:
        """Alpha as the 0-255 integer Qt uses."""
        return round(self.alpha * CHANNEL_MAX)

    @property
    def rgb(self) -> tuple[int, int, int]:
        """The three colour channels, ignoring alpha."""
        return (self.red, self.green, self.blue)

    # -- serialization ------------------------------------------------------

    @property
    def hex(self) -> str:
        """Lowercase ``#rrggbb``, ignoring alpha."""
        return f"#{self.red:02x}{self.green:02x}{self.blue:02x}"

    @property
    def hex_rgba(self) -> str:
        """Lowercase ``#rrggbbaa``, including alpha."""
        return f"{self.hex}{self.alpha_255:02x}"

    @property
    def css(self) -> str:
        """The form to emit into a stylesheet.

        Opaque colours become ``#rrggbb``; translucent colours become
        ``rgba(r, g, b, a)`` with an *integer* alpha, which is the notation Qt's
        stylesheet parser handles most reliably.
        """
        if self.is_opaque:
            return self.hex
        return f"rgba({self.red}, {self.green}, {self.blue}, {self.alpha_255})"

    def __str__(self) -> str:
        return self.css

    # -- compositing --------------------------------------------------------

    def composite_over(self, background: Color) -> Color:
        """Flatten this colour onto an opaque ``background``.

        Needed because contrast can only be measured between opaque colours,
        and several specification values are deliberately translucent.

        Args:
            background: The colour underneath. Must be opaque.

        Returns:
            The resulting opaque colour.

        Raises:
            ValueError: If ``background`` is translucent.
        """
        if not background.is_opaque:
            raise ValueError("Cannot composite over a translucent background")
        if self.is_opaque:
            return self
        blend = self.alpha
        return Color(
            round(self.red * blend + background.red * (1.0 - blend)),
            round(self.green * blend + background.green * (1.0 - blend)),
            round(self.blue * blend + background.blue * (1.0 - blend)),
        )


def _linearize(channel: int) -> float:
    """Convert an 8-bit sRGB channel to linear light, per WCAG 2.2."""
    normalized = channel / CHANNEL_MAX
    if normalized <= _SRGB_LINEAR_THRESHOLD:
        return normalized / _SRGB_LINEAR_DIVISOR
    return ((normalized + _SRGB_GAMMA_OFFSET) / _SRGB_GAMMA_DIVISOR) ** _SRGB_GAMMA_EXPONENT


def relative_luminance(color: Color) -> float:
    """Return the WCAG 2.2 relative luminance of an opaque colour.

    Raises:
        ValueError: If ``color`` is translucent. Composite it first with
            :meth:`Color.composite_over`.
    """
    if not color.is_opaque:
        raise ValueError("Relative luminance is only defined for opaque colours")
    return (
        _LUMINANCE_RED_WEIGHT * _linearize(color.red)
        + _LUMINANCE_GREEN_WEIGHT * _linearize(color.green)
        + _LUMINANCE_BLUE_WEIGHT * _linearize(color.blue)
    )


def contrast_ratio(foreground: Color, background: Color) -> float:
    """Return the WCAG 2.2 contrast ratio between two colours, 1.0 to 21.0.

    A translucent ``foreground`` is composited onto ``background`` first, so the
    result reflects what a user actually sees.

    Args:
        foreground: Text or icon colour.
        background: The opaque surface behind it.

    Returns:
        The contrast ratio. WCAG AA requires 4.5 for body text, 3.0 for large
        text and for non-text interface components.
    """
    flattened = foreground.composite_over(background)
    lighter, darker = sorted(
        (relative_luminance(flattened), relative_luminance(background)), reverse=True
    )
    return (lighter + _CONTRAST_OFFSET) / (darker + _CONTRAST_OFFSET)


@dataclass(frozen=True, slots=True)
class GradientStop:
    """One stop of a :class:`LinearGradient`.

    Attributes:
        position: Position along the gradient axis, 0.0 to 1.0.
        color: Colour at that position.
    """

    position: float
    color: Color

    def __post_init__(self) -> None:
        if not 0.0 <= self.position <= 1.0:
            raise ValueError(f"GradientStop.position must be 0.0-1.0, got {self.position}")


@dataclass(frozen=True, slots=True)
class LinearGradient:
    """An immutable linear gradient.

    Attributes:
        angle_degrees: CSS-style angle; 135 runs from top-left to bottom-right.
        stops: Ordered stops, at least two.
    """

    angle_degrees: float
    stops: tuple[GradientStop, ...]

    def __post_init__(self) -> None:
        if len(self.stops) < 2:
            raise ValueError("A gradient needs at least two stops")
        positions = [stop.position for stop in self.stops]
        if positions != sorted(positions):
            raise ValueError("Gradient stops must be ordered by position")

    @property
    def css(self) -> str:
        """CSS ``linear-gradient(...)`` notation.

        Qt stylesheets do not understand this function; it exists for
        documentation, previews and future non-Qt renderers. Qt painting goes
        through :mod:`aashi.ui.themes.qt_adapters` instead.
        """
        rendered = ", ".join(f"{stop.color.css} {stop.position * 100:g}%" for stop in self.stops)
        return f"linear-gradient({self.angle_degrees:g}deg, {rendered})"


@dataclass(frozen=True, slots=True)
class SurfaceColors:
    """Background colours, ordered from furthest back to closest to the user.

    The specification permits a maximum of four opaque layers; adding a fifth
    is a design smell rather than a token gap. Two values deliberately go
    beyond that ceiling: :attr:`glass_highlight` (a one-pixel line, not a
    layer) and :attr:`user_bubble` (a UI-02C decision that introduces a sixth
    opaque fill, because the accent-driven user bubble proved too heavy for
    compact messages — see :mod:`aashi.ui.themes.definitions`).

    Attributes:
        canvas: The application backdrop.
        primary: Default panel and content surface.
        elevated: Raised surfaces such as popovers and floating panels.
        nested: Recessed surfaces inside a panel, such as input wells.
        glass: Translucent surface used with a backdrop blur.
        glass_highlight: One-pixel inner highlight along a glass surface's top.
        user_bubble: Neutral fill for user chat bubbles. Distinct from the
            accent-driven palette, so a message reads as belonging to the user
            without shouting.
    """

    canvas: Color
    primary: Color
    elevated: Color
    nested: Color
    glass: Color
    glass_highlight: Color
    user_bubble: Color


@dataclass(frozen=True, slots=True)
class TextColors:
    """Foreground colours for text and icons.

    Attributes:
        primary: Default reading colour.
        secondary: Supporting text and inactive labels.
        tertiary: Hints and disabled text. Never used for essential content.
        inverse: Text drawn on an accent or otherwise inverted fill.
    """

    primary: Color
    secondary: Color
    tertiary: Color
    inverse: Color

    @property
    def disabled(self) -> Color:
        """Disabled text. The specification reuses the tertiary value."""
        return self.tertiary


@dataclass(frozen=True, slots=True)
class BorderColors:
    """Separator and outline colours.

    Attributes:
        subtle: Default hairline between surfaces.
        strong: Emphasised outline for interactive containers.
        focus: Keyboard focus ring.
    """

    subtle: Color
    strong: Color
    focus: Color


@dataclass(frozen=True, slots=True)
class AccentColors:
    """The brand accent and its derived fills.

    Attributes:
        base: Flat accent for controls, links and selection.
        tint: Low-opacity accent wash for selected rows and soft fills.
        tint_hover: The same wash at hover strength.
        on_accent: Text and icon colour drawn on top of :attr:`base`.
        gradient: The violet-to-blue gradient reserved for AI-state surfaces.
    """

    base: Color
    tint: Color
    tint_hover: Color
    on_accent: Color
    gradient: LinearGradient


@dataclass(frozen=True, slots=True)
class SemanticColor:
    """One status role, split by the job each variant does.

    Splitting the role matters because a colour that reads well as a 2px status
    bar on white may fail WCAG AA as body text on the same surface. Widgets pick
    the variant that matches their usage instead of tinting an all-purpose value.

    Attributes:
        base: Fills, icons, bars and borders — non-text usage.
        text: Text on this theme's surfaces. Meets WCAG AA for body text.
        tint: Low-opacity wash for banner and badge backgrounds.
    """

    base: Color
    text: Color
    tint: Color


@dataclass(frozen=True, slots=True)
class StatusColors:
    """The four status roles.

    Attributes:
        success: Completion and healthy state.
        warning: Degraded state or a reversible risk.
        danger: Failure and destructive actions.
        information: Neutral notices carrying no judgement.
    """

    success: SemanticColor
    warning: SemanticColor
    danger: SemanticColor
    information: SemanticColor


@dataclass(frozen=True, slots=True)
class ColorPalette:
    """The complete set of colour tokens for one theme.

    Attributes:
        surface: Background layers.
        text: Foreground colours.
        border: Separators and outlines.
        accent: Brand accent and derived fills.
        status: Success, warning, danger and information roles.
        scrim: Full-screen dimming behind modal and overlay surfaces.
        shadow: Ambient shadow colour, used only by floating tiers.
    """

    surface: SurfaceColors
    text: TextColors
    border: BorderColors
    accent: AccentColors
    status: StatusColors
    scrim: Color
    shadow: Color
