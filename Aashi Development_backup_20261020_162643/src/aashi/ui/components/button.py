"""Aashi button component.

The first component in the library. Composable from design tokens and the active
theme only — no literal colour values. Three variants (primary, secondary,
ghost) across four states (default, hover, pressed, disabled).

The button re-styles itself whenever the owning :class:`ThemeManager` reports a
change — theme or reduced motion — so it stays in sync with the application and
never needs to be told to refresh.

State feedback is applied instantly via QSS, which is exactly the behaviour the
motion tokens prescribe under reduced motion: feedback carries information and
must not be removed, only its animation. Connecting to the manager's motion
signal keeps this component ready for a future animated variant.
"""

from __future__ import annotations

from enum import StrEnum

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton

from aashi.ui.themes.definitions import Theme
from aashi.ui.themes.manager import ThemeManager
from aashi.ui.themes.qss import qss_variables
from aashi.ui.themes.qt_adapters import to_qfont
from aashi.ui.tokens.color import Color
from aashi.ui.tokens.typography import TextRole, style_for

__all__ = ["AashiButton", "ButtonVariant"]


class ButtonVariant(StrEnum):
    """The three sanctioned button styles.

    Attributes:
        PRIMARY: Solid accent fill — the single call to action.
        SECONDARY: Surface fill with an outline — the alternative action.
        GHOST: No fill until hover — low-emphasis actions in toolbars and panels.
    """

    PRIMARY = "primary"
    SECONDARY = "secondary"
    GHOST = "ghost"


# UI-02B decision: the palette defines no solid accent hover, so the primary
# button's hover/pressed fills are derived from the accent by compositing a
# translucent wash over it — light in dark themes (the glass highlight), a
# near-black tint in light themes, and pressed always darkens. Every wash colour
# comes from the theme; only the wash opacities are constants chosen here.
_PRIMARY_HOVER_LIGHT_ALPHA: float = 0.06
_PRIMARY_PRESSED_ALPHA_DARK: float = 0.24
_PRIMARY_PRESSED_ALPHA_LIGHT: float = 0.12


def _primary_hover(theme: Theme) -> Color:
    """The hover fill for a primary button: the accent, slightly lifted."""
    accent = theme.palette.accent.base
    wash = (
        theme.palette.surface.glass_highlight
        if theme.is_dark
        else theme.palette.scrim.with_alpha(_PRIMARY_HOVER_LIGHT_ALPHA)
    )
    return wash.composite_over(accent)


def _primary_pressed(theme: Theme) -> Color:
    """The pressed fill for a primary button: the accent, depressed."""
    accent = theme.palette.accent.base
    alpha = _PRIMARY_PRESSED_ALPHA_DARK if theme.is_dark else _PRIMARY_PRESSED_ALPHA_LIGHT
    return theme.palette.scrim.with_alpha(alpha).composite_over(accent)


def _high_contrast_rules(variables: dict[str, str], variant: ButtonVariant) -> str:
    """High-contrast overrides: permanent outline, no translucent fills."""
    rules = (
        "AashiButton {\n"
        f"  border-color: {variables['color.border.strong']};\n"
        "}\n"
    )
    if variant is ButtonVariant.GHOST:
        # Translucent washes are disabled; the ghost hover becomes a solid lift.
        rules += (
            "AashiButton:hover {\n"
            f"  background-color: {variables['color.surface.elevated']};\n"
            "}\n"
            "AashiButton:pressed {\n"
            f"  background-color: {variables['color.surface.nested']};\n"
            "}\n"
        )
    return rules


class AashiButton(QPushButton):
    """A theme-aware button with primary, secondary and ghost variants.

    Args:
        text: The button label.
        theme_manager: The active theme manager; the button follows it for life.
        variant: The initial :class:`ButtonVariant`.
        border_radius_px: Optional pixel override for the corner radius. Used
            for square icon buttons that need to become circles (half their
            side length); the token radius applies when left as ``None``.
        parent: Optional Qt parent.
    """

    def __init__(
        self,
        text: str,
        theme_manager: ThemeManager,
        variant: ButtonVariant = ButtonVariant.PRIMARY,
        border_radius_px: int | None = None,
        parent=None,
    ) -> None:
        super().__init__(text, parent)
        self._theme_manager = theme_manager
        self._variant = variant
        self._border_radius_px = border_radius_px
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        theme_manager.theme_changed.connect(self._restyle)
        theme_manager.reduced_motion_changed.connect(self._restyle)
        self._restyle()

    @property
    def variant(self) -> ButtonVariant:
        """The current variant."""
        return self._variant

    def set_variant(self, variant: ButtonVariant) -> None:
        """Switch variant and re-style in place."""
        if variant is self._variant:
            return
        self._variant = variant
        self._restyle()

    def _restyle(self, *_: object) -> None:
        """Regenerate the font and stylesheet from the active theme."""
        self.setFont(to_qfont(style_for(TextRole.BODY)))
        self.setStyleSheet(self._build_stylesheet(self._theme_manager.theme))

    def _build_stylesheet(self, theme: Theme) -> str:
        variables = qss_variables(theme)
        radius = (
            f"{self._border_radius_px}px"
            if self._border_radius_px is not None
            else variables["radius.medium"]
        )
        stylesheet = (
            "AashiButton {\n"
            f"  min-height: {variables['control.height.default']};\n"
            f"  padding: 0 {variables['space.200']};\n"
            f"  border-radius: {radius};\n"
            f"  border: {variables['border.hairline']} solid transparent;\n"
            "}\n"
            "AashiButton:focus {\n"
            f"  border: {variables['border.focusRing']} solid "
            f"{variables['color.border.focus']};\n"
            "}\n"
        )
        stylesheet += self._variant_rules(theme, variables)
        if theme.high_contrast:
            stylesheet += _high_contrast_rules(variables, self._variant)
        return stylesheet

    def _variant_rules(self, theme: Theme, variables: dict[str, str]) -> str:
        variant = self._variant
        if variant is ButtonVariant.PRIMARY:
            return (
                "AashiButton {\n"
                f"  background-color: {variables['color.accent']};\n"
                f"  color: {variables['color.accent.on']};\n"
                "}\n"
                "AashiButton:hover {\n"
                f"  background-color: {_primary_hover(theme).css};\n"
                "}\n"
                "AashiButton:pressed {\n"
                f"  background-color: {_primary_pressed(theme).css};\n"
                "}\n"
                "AashiButton:disabled {\n"
                f"  background-color: {variables['color.accent.tint']};\n"
                f"  color: {variables['color.text.disabled']};\n"
                "}\n"
            )
        if variant is ButtonVariant.SECONDARY:
            return (
                "AashiButton {\n"
                f"  background-color: {variables['color.surface']};\n"
                f"  color: {variables['color.text']};\n"
                f"  border-color: {variables['color.border']};\n"
                "}\n"
                "AashiButton:hover {\n"
                f"  background-color: {variables['color.surface.elevated']};\n"
                f"  border-color: {variables['color.border.strong']};\n"
                "}\n"
                "AashiButton:pressed {\n"
                f"  background-color: {variables['color.surface.nested']};\n"
                "}\n"
                "AashiButton:disabled {\n"
                f"  color: {variables['color.text.disabled']};\n"
                "}\n"
            )
        return (
            "AashiButton {\n"
            "  background-color: transparent;\n"
            f"  color: {variables['color.text']};\n"
            "}\n"
            "AashiButton:hover {\n"
            f"  background-color: {variables['color.accent.tintHover']};\n"
            "}\n"
            "AashiButton:pressed {\n"
            f"  background-color: {variables['color.accent.tint']};\n"
            "}\n"
            "AashiButton:disabled {\n"
            f"  color: {variables['color.text.disabled']};\n"
            "}\n"
        )
