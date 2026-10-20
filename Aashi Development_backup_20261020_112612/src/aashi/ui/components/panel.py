"""Aashi panel component.

A reusable container card composed from the theme surface, border and radius
tokens. Two variants (elevated, flat) and two border weights (hairline, strong).
The panel re-styles itself whenever the owning :class:`ThemeManager` reports a
theme change, and lays its content out inset by the spacing token.

Children are added to ``panel.layout()``; the panel's own layout provides the
token padding.
"""

from __future__ import annotations

from enum import StrEnum

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout, QWidget

from aashi.ui.themes.definitions import Theme
from aashi.ui.themes.manager import ThemeManager
from aashi.ui.themes.qss import qss_variables
from aashi.ui.tokens.spacing import Space

__all__ = ["AashiPanel", "PanelVariant", "PanelBorder"]


class PanelVariant(StrEnum):
    """The two sanctioned panel heights.

    Attributes:
        ELEVATED: A raised surface (``surface.elevated``) — cards and popovers.
        FLAT: Level with the surrounding canvas (``surface``) — inline panels.
    """

    ELEVATED = "elevated"
    FLAT = "flat"


class PanelBorder(StrEnum):
    """The two sanctioned panel outlines.

    Attributes:
        HAIRLINE: The subtle ``color.border`` — quiet default.
        STRONG: The ``color.border.strong`` — emphasis and separation.
    """

    HAIRLINE = "hairline"
    STRONG = "strong"


class AashiPanel(QWidget):
    """A theme-aware container card.

    Args:
        theme_manager: The active theme manager; the panel follows it for life.
        variant: The initial :class:`PanelVariant`.
        border: The initial :class:`PanelBorder`.
        parent: Optional Qt parent.
    """

    def __init__(
        self,
        theme_manager: ThemeManager,
        variant: PanelVariant = PanelVariant.ELEVATED,
        border: PanelBorder = PanelBorder.HAIRLINE,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._theme_manager = theme_manager
        self._variant = variant
        self._border = border
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        padding = Space.SPACE_300.value
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(padding, padding, padding, padding)
        theme_manager.theme_changed.connect(self._restyle)
        self._restyle()

    @property
    def variant(self) -> PanelVariant:
        """The current variant."""
        return self._variant

    def set_variant(self, variant: PanelVariant) -> None:
        """Switch variant and re-style in place."""
        if variant is self._variant:
            return
        self._variant = variant
        self._restyle()

    @property
    def border(self) -> PanelBorder:
        """The current border weight."""
        return self._border

    def set_border(self, border: PanelBorder) -> None:
        """Switch border weight and re-style in place."""
        if border is self._border:
            return
        self._border = border
        self._restyle()

    def _restyle(self, *_: object) -> None:
        """Regenerate the stylesheet from the active theme."""
        self.setStyleSheet(self._build_stylesheet(self._theme_manager.theme))

    def _build_stylesheet(self, theme: Theme) -> str:
        variables = qss_variables(theme)
        background = variables[
            "color.surface.elevated"
            if self._variant is PanelVariant.ELEVATED
            else "color.surface"
        ]
        border_color = (
            variables["color.border.strong"]
            if self._border is PanelBorder.STRONG
            else variables["color.border"]
        )
        if theme.high_contrast:
            # High contrast draws a permanent visible outline.
            border_color = variables["color.border.strong"]
        return (
            "AashiPanel {\n"
            f"  background-color: {background};\n"
            f"  border: {variables['border.hairline']} solid {border_color};\n"
            f"  border-radius: {variables['radius.medium']};\n"
            "}\n"
        )
