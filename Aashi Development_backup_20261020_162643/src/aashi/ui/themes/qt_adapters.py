"""Conversions from Aashi design tokens to Qt types.

This is the boundary. Everything below it — tokens, theme definitions,
stylesheet generation — is plain data and needs no ``QApplication``; everything
above it can rely on Qt. Keeping the conversions in one module means the token
layer stays testable in isolation, and that swapping or upgrading the Qt binding
touches one file.

The functions here are pure: they build a Qt object from a token and return it.
Applying anything to a running application is
:class:`~aashi.ui.themes.manager.ThemeManager`'s responsibility.
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPointF
from PySide6.QtGui import QColor, QFont, QPalette

from aashi.ui.themes.definitions import Theme
from aashi.ui.tokens.color import Color
from aashi.ui.tokens.motion import Easing
from aashi.ui.tokens.typography import TextStyle

__all__ = ["build_qpalette", "to_qcolor", "to_qeasing_curve", "to_qfont"]

_PERCENTAGE_SPACING_BASE: float = 100.0
"""``QFont`` expresses letter spacing as a percentage where 100 means normal."""


def to_qcolor(color: Color) -> QColor:
    """Convert a token colour to a ``QColor``, preserving alpha."""
    return QColor(color.red, color.green, color.blue, color.alpha_255)


def to_qfont(style: TextStyle) -> QFont:
    """Convert a text style to a ``QFont``.

    Sizes are set in pixels rather than points so that the specification's
    values survive intact; Qt then scales them for the display's device pixel
    ratio.

    Args:
        style: The text style to realise.

    Returns:
        A configured ``QFont``. The full fallback stack is supplied, so Qt picks
        the first family actually installed.
    """
    font = QFont()
    font.setFamilies(list(style.family))
    font.setPixelSize(style.size_px)
    font.setWeight(QFont.Weight(int(style.weight)))
    # The specification forbids italics anywhere in the interface.
    font.setItalic(False)
    if style.letter_spacing_em:
        percentage = _PERCENTAGE_SPACING_BASE * (1.0 + style.letter_spacing_em)
        font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, percentage)
    if style.uppercase:
        font.setCapitalization(QFont.Capitalization.AllUppercase)
    return font


def to_qeasing_curve(easing: Easing) -> QEasingCurve:
    """Convert an easing token to a ``QEasingCurve``."""
    curve = QEasingCurve(QEasingCurve.Type.BezierSpline)
    curve.addCubicBezierSegment(
        QPointF(easing.x1, easing.y1),
        QPointF(easing.x2, easing.y2),
        QPointF(1.0, 1.0),
    )
    return curve


def build_qpalette(theme: Theme) -> QPalette:
    """Build the ``QPalette`` for a theme.

    ``QPalette`` is Qt's native mechanism for application-wide colour, and it
    reaches places a stylesheet cannot: native dialogs, text selection, the
    disabled state of built-in widgets. Aashi drives it from the same tokens as
    the stylesheet so the two can never disagree.

    Args:
        theme: The theme to realise.

    Returns:
        A palette covering the active and disabled colour groups.
    """
    palette = theme.palette
    result = QPalette()

    surface = palette.surface
    text = palette.text
    accent = palette.accent

    canvas = to_qcolor(surface.canvas)
    primary_surface = to_qcolor(surface.primary)
    elevated = to_qcolor(surface.elevated)
    nested = to_qcolor(surface.nested)
    primary_text = to_qcolor(text.primary)
    disabled_text = to_qcolor(text.disabled)

    role = QPalette.ColorRole
    group = QPalette.ColorGroup

    result.setColor(role.Window, canvas)
    result.setColor(role.WindowText, primary_text)
    # Base is the background of editable widgets: a recessed well, not the panel.
    result.setColor(role.Base, nested)
    result.setColor(role.AlternateBase, primary_surface)
    result.setColor(role.Text, primary_text)
    result.setColor(role.PlaceholderText, to_qcolor(text.tertiary))
    result.setColor(role.Button, elevated)
    result.setColor(role.ButtonText, primary_text)
    result.setColor(role.ToolTipBase, elevated)
    result.setColor(role.ToolTipText, primary_text)
    result.setColor(role.Highlight, to_qcolor(accent.base))
    result.setColor(role.HighlightedText, to_qcolor(accent.on_accent))
    result.setColor(role.Link, to_qcolor(accent.base))
    result.setColor(role.LinkVisited, to_qcolor(accent.base))
    result.setColor(role.BrightText, to_qcolor(palette.status.danger.text))
    result.setColor(role.Mid, to_qcolor(palette.border.subtle))
    result.setColor(role.Dark, to_qcolor(palette.border.strong))
    result.setColor(role.Shadow, to_qcolor(palette.shadow))

    for disabled_role in (role.WindowText, role.Text, role.ButtonText):
        result.setColor(group.Disabled, disabled_role, disabled_text)
    result.setColor(group.Disabled, role.Highlight, nested)
    result.setColor(group.Disabled, role.HighlightedText, disabled_text)

    return result
