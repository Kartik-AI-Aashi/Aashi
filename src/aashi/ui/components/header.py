"""Aashi header component.

The top chrome of a window: the application title on the primary surface,
separated from the content below by a hairline. The title uses the
:class:`~aashi.ui.tokens.typography.TextRole.TITLE` role and the header paints
the ``color.surface`` fill, so it reads as a bar rather than as a card.

The title sits left with a trailing stretch, so later modules can add actions to
the right-hand edge through ``header.layout()``. The header re-styles itself
whenever the owning :class:`ThemeManager` reports a theme change.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from aashi.constants import APP_NAME
from aashi.ui.themes.definitions import Theme
from aashi.ui.themes.manager import ThemeManager
from aashi.ui.themes.qss import qss_variables
from aashi.ui.themes.qt_adapters import to_qfont
from aashi.ui.tokens.spacing import SPACING
from aashi.ui.tokens.typography import TextRole, style_for

__all__ = ["AashiHeader"]


class AashiHeader(QWidget):
    """A theme-aware application header.

    Args:
        theme_manager: The active theme manager; the header follows it for life.
        title: The header title. Defaults to the application name.
        parent: Optional Qt parent.
    """

    def __init__(
        self,
        theme_manager: ThemeManager,
        title: str = APP_NAME,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._theme_manager = theme_manager

        # A plain QWidget paints no background; QSS needs this to draw the fill.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._title = QLabel(title, self)
        self._title.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            SPACING.gutter_compact,
            SPACING.control_padding_vertical,
            SPACING.gutter_compact,
            SPACING.control_padding_vertical,
        )
        layout.setSpacing(SPACING.inline_gap)
        layout.addWidget(self._title)
        # Reserve the trailing edge for actions added by later modules.
        layout.addStretch(1)

        theme_manager.theme_changed.connect(self._restyle)
        self._restyle()

    @property
    def title(self) -> str:
        """The header's title text."""
        return self._title.text()

    def set_title(self, title: str) -> None:
        """Replace the header's title text."""
        self._title.setText(title)

    def _restyle(self, *_: object) -> None:
        """Regenerate the font and stylesheet from the active theme."""
        theme = self._theme_manager.theme
        self._title.setFont(to_qfont(style_for(TextRole.TITLE)))
        self.setStyleSheet(self._build_stylesheet(theme))

    def _build_stylesheet(self, theme: Theme) -> str:
        variables = qss_variables(theme)
        return (
            "AashiHeader {\n"
            f"  background-color: {variables['color.surface']};\n"
            f"  color: {variables['color.text']};\n"
            f"  border-bottom: {variables['border.hairline']} solid "
            f"{variables['color.border']};\n"
            "}\n"
        )
