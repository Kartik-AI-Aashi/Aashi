"""Typography tokens.

The approved UI/UX specification defines exactly six text roles. Widgets choose
a role; they never invent a font size, weight or line height. Adding a seventh
role is a specification change, not an implementation detail.

Font *families* are expressed as ordered fallback stacks rather than single
names, because Segoe UI Variable and Cascadia Code ship with Windows 11 but are
not guaranteed on the developer machines and CI runners the test suite also has
to satisfy.

Nothing here imports Qt. :mod:`aashi.ui.themes.qt_adapters` turns a
:class:`TextStyle` into a ``QFont``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import IntEnum, StrEnum
from types import MappingProxyType
from typing import Final

__all__ = [
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
]

FONT_FAMILY_UI: Final[tuple[str, ...]] = (
    "Segoe UI Variable Text",
    "Segoe UI Variable",
    "Segoe UI",
    "Inter",
    "sans-serif",
)
"""Interface font stack. Segoe UI Variable first, per the specification."""

FONT_FAMILY_CODE: Final[tuple[str, ...]] = (
    "Cascadia Code",
    "Cascadia Mono",
    "Consolas",
    "monospace",
)
"""Technical font stack for code, logs, identifiers and terminal output."""


class FontWeight(IntEnum):
    """The three sanctioned font weights.

    Introducing a fourth weight produces visual inconsistency that is very hard
    to unpick later, so the scale is closed on purpose.
    """

    REGULAR = 400
    MEDIUM = 500
    SEMIBOLD = 600


class TextRole(StrEnum):
    """The six text roles defined by the specification.

    Attributes:
        DISPLAY: Reserved for a single hero string per screen.
        TITLE: Window and primary view titles.
        SECTION: Group headings inside a view.
        BODY: Default reading size for running text and controls.
        CAPTION: Secondary metadata, timestamps and helper text.
        MICRO: Uppercase eyebrow labels. Never used for sentences.
    """

    DISPLAY = "display"
    TITLE = "title"
    SECTION = "section"
    BODY = "body"
    CAPTION = "caption"
    MICRO = "micro"


@dataclass(frozen=True, slots=True)
class TextStyle:
    """One fully specified text style.

    Attributes:
        role: The role this style implements.
        size_px: Font size in logical pixels.
        line_height_px: Line box height in logical pixels.
        weight: Numeric font weight.
        letter_spacing_em: Tracking, expressed in em so it scales with size.
        uppercase: Whether the role is always rendered in capitals.
        family: Ordered font fallback stack.
    """

    role: TextRole
    size_px: int
    line_height_px: int
    weight: FontWeight
    letter_spacing_em: float = 0.0
    uppercase: bool = False
    family: tuple[str, ...] = FONT_FAMILY_UI

    @property
    def letter_spacing_px(self) -> float:
        """Tracking converted to logical pixels at this style's size."""
        return self.letter_spacing_em * self.size_px

    @property
    def line_height_ratio(self) -> float:
        """Line height as a multiple of font size, for renderers that want it."""
        return self.line_height_px / self.size_px

    @property
    def css_font_family(self) -> str:
        """The family stack as a CSS/QSS ``font-family`` value."""
        return ", ".join(f'"{name}"' if " " in name else name for name in self.family)

    def with_family(self, family: tuple[str, ...]) -> TextStyle:
        """Return a copy of this style using a different font family stack."""
        return replace(self, family=family)


_TYPOGRAPHY: Final[dict[TextRole, TextStyle]] = {
    TextRole.DISPLAY: TextStyle(TextRole.DISPLAY, 32, 40, FontWeight.SEMIBOLD),
    TextRole.TITLE: TextStyle(TextRole.TITLE, 24, 32, FontWeight.SEMIBOLD),
    TextRole.SECTION: TextStyle(TextRole.SECTION, 18, 26, FontWeight.SEMIBOLD),
    TextRole.BODY: TextStyle(TextRole.BODY, 14, 22, FontWeight.REGULAR),
    TextRole.CAPTION: TextStyle(TextRole.CAPTION, 12, 18, FontWeight.REGULAR),
    TextRole.MICRO: TextStyle(
        TextRole.MICRO,
        11,
        16,
        FontWeight.MEDIUM,
        letter_spacing_em=0.04,
        uppercase=True,
    ),
}

TYPOGRAPHY: Final[Mapping[TextRole, TextStyle]] = MappingProxyType(_TYPOGRAPHY)
"""Read-only mapping of every text role to its style."""


def style_for(role: TextRole) -> TextStyle:
    """Return the style for ``role``.

    Preferred over indexing :data:`TYPOGRAPHY` directly: it keeps call sites
    readable and leaves one place to add future per-density overrides.
    """
    return TYPOGRAPHY[role]


def code_style(role: TextRole = TextRole.BODY) -> TextStyle:
    """Return ``role``'s metrics rendered in the technical font stack.

    Code and interface text share a vertical rhythm; only the family differs.
    """
    return style_for(role).with_family(FONT_FAMILY_CODE)


# ---------------------------------------------------------------------------
# Prose rhythm
#
# Line length and paragraph rhythm are typographic decisions, so they live with
# the type scale rather than with layout spacing.
# ---------------------------------------------------------------------------

MEASURE_PROSE_PX: Final[int] = 680
"""Maximum line length for running prose, per the specification."""

MEASURE_DESCRIPTION_PX: Final[int] = 560
"""Maximum line length for settings descriptions and helper text."""

PARAGRAPH_GAP_PX: Final[int] = 12
"""Vertical gap between paragraphs."""

LIST_ITEM_GAP_PX: Final[int] = 8
"""Vertical gap between list items."""

USE_TABULAR_FIGURES: Final[bool] = True
"""Whether data-dense contexts request tabular (fixed-width) numerals."""

ALLOW_ITALICS: Final[bool] = False
"""The specification forbids italics anywhere in the interface."""
