"""Token-driven Qt stylesheet generation.

Qt stylesheets have no variables, which is exactly why hand-written QSS drifts
away from a design system: every colour has to be typed out again, and the tenth
copy is always the one that gets missed. This module closes that gap with a
small substitution engine.

A template writes ``{{color.accent}}``; :func:`render_qss` replaces it with the
active theme's value. An unknown placeholder raises rather than resolving to an
empty string, because a silently missing colour produces a stylesheet that looks
almost right and is very hard to debug.

UI-02A provides only the *foundation* plus an application-wide base stylesheet.
Component styling belongs to the component library module and must be written as
templates fed through this engine, never as literal values.

Nothing here imports Qt: the output is a string, and applying it is the theme
manager's job.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Final

from aashi.ui.themes.definitions import Theme
from aashi.ui.tokens.borders import BorderWidth
from aashi.ui.tokens.controls import ControlHeight, IconSize
from aashi.ui.tokens.radius import Radius
from aashi.ui.tokens.spacing import Space
from aashi.ui.tokens.typography import (
    FONT_FAMILY_CODE,
    TYPOGRAPHY,
    TextRole,
    style_for,
)

__all__ = [
    "BASE_STYLESHEET_TEMPLATE",
    "QssTemplateError",
    "build_base_stylesheet",
    "qss_variables",
    "render_qss",
]

_PLACEHOLDER: Final[re.Pattern[str]] = re.compile(r"\{\{\s*([A-Za-z0-9_.\-]+)\s*\}\}")


class QssTemplateError(ValueError):
    """Raised when a stylesheet template references a token that does not exist."""


def qss_variables(theme: Theme) -> Mapping[str, str]:
    """Return every design token as a stylesheet-ready string.

    Only values a Qt stylesheet can actually consume are included — colours,
    fonts, and pixel geometry. Durations and shadows are omitted because QSS
    cannot express them; they are read from
    :mod:`aashi.ui.tokens.motion` and :mod:`aashi.ui.tokens.elevation` directly.

    Args:
        theme: The theme whose colours the map should carry.

    Returns:
        An immutable mapping from token name to QSS value.
    """
    palette = theme.palette
    variables: dict[str, str] = {}

    # -- colour -------------------------------------------------------------
    surface = palette.surface
    variables.update(
        {
            "color.canvas": surface.canvas.css,
            "color.surface": surface.primary.css,
            "color.surface.elevated": surface.elevated.css,
            "color.surface.nested": surface.nested.css,
            "color.surface.glass": surface.glass.css,
            "color.surface.glassHighlight": surface.glass_highlight.css,
            "color.surface.userBubble": surface.user_bubble.css,
        }
    )
    text = palette.text
    variables.update(
        {
            "color.text": text.primary.css,
            "color.text.secondary": text.secondary.css,
            "color.text.tertiary": text.tertiary.css,
            "color.text.disabled": text.disabled.css,
            "color.text.inverse": text.inverse.css,
        }
    )
    border = palette.border
    variables.update(
        {
            "color.border": border.subtle.css,
            "color.border.strong": border.strong.css,
            "color.border.focus": border.focus.css,
        }
    )
    accent = palette.accent
    variables.update(
        {
            "color.accent": accent.base.css,
            "color.accent.tint": accent.tint.css,
            "color.accent.tintHover": accent.tint_hover.css,
            "color.accent.on": accent.on_accent.css,
        }
    )
    status = palette.status
    for name, semantic in (
        ("success", status.success),
        ("warning", status.warning),
        ("danger", status.danger),
        ("information", status.information),
    ):
        variables[f"color.{name}"] = semantic.base.css
        variables[f"color.{name}.text"] = semantic.text.css
        variables[f"color.{name}.tint"] = semantic.tint.css
    variables["color.scrim"] = palette.scrim.css

    # -- typography ---------------------------------------------------------
    variables["font.ui"] = style_for(TextRole.BODY).css_font_family
    variables["font.code"] = (
        style_for(TextRole.BODY).with_family(FONT_FAMILY_CODE).css_font_family
    )
    for role, style in TYPOGRAPHY.items():
        variables[f"font.{role.value}.size"] = f"{style.size_px}px"
        variables[f"font.{role.value}.lineHeight"] = f"{style.line_height_px}px"
        variables[f"font.{role.value}.weight"] = str(int(style.weight))

    # -- geometry -----------------------------------------------------------
    for space in Space:
        variables[f"space.{space.name.removeprefix('SPACE_')}"] = f"{space.value}px"
    for radius in Radius:
        variables[f"radius.{radius.name.lower()}"] = f"{radius.value}px"
    for width in BorderWidth:
        variables[f"border.{_camel(width.name)}"] = f"{width.value}px"
    for height in ControlHeight:
        variables[f"control.height.{height.name.lower()}"] = f"{height.value}px"
    for size in IconSize:
        variables[f"icon.{size.name.lower()}"] = f"{size.value}px"

    return dict(variables)


def _camel(enum_member_name: str) -> str:
    """Convert ``FOCUS_RING`` to ``focusRing`` for stylesheet-friendly names."""
    head, *tail = enum_member_name.lower().split("_")
    return head + "".join(part.capitalize() for part in tail)


def render_qss(template: str, theme: Theme) -> str:
    """Substitute every ``{{token}}`` placeholder in ``template``.

    Args:
        template: Stylesheet source containing ``{{token.name}}`` placeholders.
        theme: The theme supplying values.

    Returns:
        The rendered stylesheet.

    Raises:
        QssTemplateError: If the template references any unknown token. The
            error names every offending placeholder at once, so a template is
            fixed in a single pass rather than one error at a time.
    """
    variables = qss_variables(theme)
    unknown: list[str] = []

    def substitute(match: re.Match[str]) -> str:
        name = match.group(1)
        value = variables.get(name)
        if value is None:
            unknown.append(name)
            return ""
        return value

    rendered = _PLACEHOLDER.sub(substitute, template)
    if unknown:
        names = ", ".join(sorted(set(unknown)))
        raise QssTemplateError(f"Unknown design token(s) in stylesheet template: {names}")
    return rendered


BASE_STYLESHEET_TEMPLATE: Final[str] = """
/* Aashi base stylesheet. Application-wide roles only.
   Component rules belong to the component library, as templates rendered
   through aashi.ui.themes.qss.render_qss. Never write a literal value here. */

QWidget {
    color: {{color.text}};
    font-family: {{font.ui}};
    font-size: {{font.body.size}};
    font-weight: {{font.body.weight}};
}

QWidget:disabled {
    color: {{color.text.disabled}};
}
""".strip()
"""The application-wide stylesheet, before token substitution.

Deliberately tiny. Background colours come from the ``QPalette`` built by
:func:`aashi.ui.themes.qt_adapters.build_qpalette`, because a blanket
``QWidget { background-color: ... }`` rule would paint every child widget
opaquely and break Qt's own compositing.
"""


def build_base_stylesheet(theme: Theme) -> str:
    """Render the application-wide stylesheet for ``theme``."""
    return render_qss(BASE_STYLESHEET_TEMPLATE, theme)
