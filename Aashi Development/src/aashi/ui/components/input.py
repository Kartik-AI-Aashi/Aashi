"""Aashi input component.

A single-line text input. The input well is the recessed ``surface.nested``
surface — the same value :func:`aashi.ui.themes.qt_adapters.build_qpalette`
assigns to ``QPalette.Base`` — so an input reads as a well cut into its
surrounding panel rather than as another panel.

The input re-styles itself whenever the owning :class:`ThemeManager` reports a
theme change. Placeholder text is styled through the ``PlaceholderText`` palette
role: Qt stylesheets have no placeholder selector, so a ``QLineEdit::placeholder``
rule would silently not paint.

``embedded=True`` strips the well entirely — transparent background, no border,
no radius — for inputs that sit inside a chrome container of their own, such as
the chat composer pill. The pill supplies the surface and the outline.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QLineEdit, QSizePolicy

from aashi.ui.themes.definitions import Theme
from aashi.ui.themes.manager import ThemeManager
from aashi.ui.themes.qss import qss_variables
from aashi.ui.themes.qt_adapters import to_qcolor, to_qfont
from aashi.ui.tokens.typography import TextRole, style_for

__all__ = ["AashiInput"]


def _high_contrast_rules(variables: dict[str, str]) -> str:
    """High-contrast override: a permanent solid outline on every input."""
    return (
        "AashiInput {\n"
        f"  border-color: {variables['color.border.strong']};\n"
        "}\n"
    )


class AashiInput(QLineEdit):
    """A theme-aware single-line text input.

    Args:
        theme_manager: The active theme manager; the input follows it for life.
        placeholder: Initial placeholder text.
        embedded: When true, render with no well of its own (transparent, no
            border) so a surrounding container such as the composer pill can
            own the chrome.
        parent: Optional Qt parent.
    """

    def __init__(
        self,
        theme_manager: ThemeManager,
        placeholder: str = "",
        embedded: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._theme_manager = theme_manager
        self._embedded = embedded
        self.setPlaceholderText(placeholder)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        # The chat composer's row centres this input and lets it stretch up to
        # its maximum width, so it must advertise that it can grow horizontally.
        policy = self.sizePolicy()
        policy.setHorizontalPolicy(QSizePolicy.Policy.Expanding)
        self.setSizePolicy(policy)
        theme_manager.theme_changed.connect(self._restyle)
        self._restyle()

    def _restyle(self, *_: object) -> None:
        """Regenerate the font, stylesheet and placeholder colour."""
        theme = self._theme_manager.theme
        self.setFont(to_qfont(style_for(TextRole.BODY)))
        self.setStyleSheet(self._build_stylesheet(theme))
        self._style_placeholder(theme)

    def _style_placeholder(self, theme: Theme) -> None:
        """Style the placeholder via the palette role QLineEdit paints it from."""
        palette = self.palette()
        palette.setColor(
            QPalette.ColorRole.PlaceholderText,
            to_qcolor(theme.palette.text.tertiary),
        )
        self.setPalette(palette)

    def _build_stylesheet(self, theme: Theme) -> str:
        variables = qss_variables(theme)
        if self._embedded:
            # Inside the composer pill the pill owns the chrome, so the input
            # is a bare text field: no well, no border, no radius. The pill's
            # own stylesheet supplies the high-contrast outline.
            return (
                "AashiInput {\n"
                f"  min-height: {variables['control.height.large']};\n"
                "  padding: 0;\n"
                "  background-color: transparent;\n"
                f"  color: {variables['color.text']};\n"
                "  border: none;\n"
                "}\n"
                "AashiInput:focus {\n"
                "  border: none;\n"
                "}\n"
                "AashiInput:disabled {\n"
                f"  color: {variables['color.text.disabled']};\n"
                "}\n"
            )

        stylesheet = (
            "AashiInput {\n"
            f"  min-height: {variables['control.height.large']};\n"
            f"  padding: 0 {variables['space.300']};\n"
            f"  background-color: {variables['color.surface.nested']};\n"
            f"  color: {variables['color.text']};\n"
            f"  border: {variables['border.hairline']} solid "
            f"{variables['color.border']};\n"
            f"  border-radius: {variables['radius.large']};\n"
            "}\n"
            "AashiInput:focus {\n"
            f"  border: {variables['border.focusRing']} solid "
            f"{variables['color.border.focus']};\n"
            "}\n"
            "AashiInput:disabled {\n"
            f"  color: {variables['color.text.disabled']};\n"
            "}\n"
        )
        if theme.high_contrast:
            stylesheet += _high_contrast_rules(variables)
        return stylesheet
