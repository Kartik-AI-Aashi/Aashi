"""TEMPORARY foundation and theme-preview window.

This window is scaffolding, not design. UI-01 created it to prove that Python
starts, PySide6 loads, ``QApplication`` initializes, the package imports
correctly and the Qt event loop runs. UI-02A extends it just far enough to *see*
the theme engine working: switch between Dark, Light and System, toggle reduced
motion, and check every surface, text and status colour side by side.

It is not, and must not become, the Aashi interface. A later UI module deletes
this file and replaces it with the real window.

Two rules still hold even here:

- Every visual value comes from a design token. The swatches are rendered
  through :func:`aashi.ui.themes.qss.render_qss`, so the preview exercises the
  same substitution engine the component library will use, and a mistyped token
  name fails loudly instead of silently painting nothing.
- Without a theme manager the window degrades to exactly its UI-01 behaviour, so
  the foundation smoke tests keep testing the foundation.
"""

from __future__ import annotations

from typing import Final, NamedTuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from aashi.constants import (
    APP_VERSION,
    BOOTSTRAP_WINDOW_MIN_HEIGHT,
    BOOTSTRAP_WINDOW_MIN_WIDTH,
    BOOTSTRAP_WINDOW_TEXT,
    BOOTSTRAP_WINDOW_TITLE,
)
from aashi.ui.accessibility.reduced_motion import MotionPreference
from aashi.ui.themes.manager import ThemeManager
from aashi.ui.themes.mode import ThemeMode
from aashi.ui.themes.qss import qss_variables, render_qss
from aashi.ui.themes.qt_adapters import to_qfont
from aashi.ui.tokens.controls import ControlHeight
from aashi.ui.tokens.motion import MotionRole
from aashi.ui.tokens.radius import Radius
from aashi.ui.tokens.spacing import LAYOUT, SPACING, Space
from aashi.ui.tokens.typography import TYPOGRAPHY, TextRole, style_for

__all__ = ["FoundationWindow"]

# Scaffolding geometry, derived from layout tokens so that even the throwaway
# window does not introduce numbers of its own.
_PREVIEW_DEFAULT_WIDTH: Final[int] = LAYOUT.content_reading + LAYOUT.context_panel
_PREVIEW_DEFAULT_HEIGHT: Final[int] = LAYOUT.content_reading
_SWATCH_HEIGHT: Final[int] = Space.SPACE_800
_SWATCH_COLUMNS: Final[int] = 4

_SURFACE_TOKENS: Final[tuple[tuple[str, str], ...]] = (
    ("Canvas", "color.canvas"),
    ("Primary surface", "color.surface"),
    ("Elevated surface", "color.surface.elevated"),
    ("Nested surface", "color.surface.nested"),
)

_FOREGROUND_TOKENS: Final[tuple[tuple[str, str], ...]] = (
    ("Primary text", "color.text"),
    ("Secondary text", "color.text.secondary"),
    ("Tertiary text", "color.text.tertiary"),
    ("Accent", "color.accent"),
    ("Success", "color.success.text"),
    ("Warning", "color.warning.text"),
    ("Danger", "color.danger.text"),
    ("Information", "color.information.text"),
)

_MODE_BUTTONS: Final[tuple[tuple[str, ThemeMode], ...]] = (
    ("Dark", ThemeMode.DARK),
    ("Light", ThemeMode.LIGHT),
    ("System", ThemeMode.SYSTEM),
)

# A surface is judged as an area, so it is painted as the swatch background. A
# foreground colour is judged as text: shown as a large block it tells you
# nothing about whether it is readable, so it is drawn as a label on the primary
# surface instead.
_SURFACE_TEMPLATE: Final[str] = (
    "#{name} {{"
    " background-color: {{{{{token}}}}};"
    " border: {{{{border.hairline}}}} solid {{{{color.border}}}};"
    " border-radius: {{{{radius.medium}}}}; }}"
)
_FOREGROUND_TEMPLATE: Final[str] = (
    "#{name} {{"
    " background-color: {{{{color.surface}}}};"
    " border: {{{{border.hairline}}}} solid {{{{color.border}}}};"
    " border-radius: {{{{radius.medium}}}}; }}"
    " #{name} QLabel {{ color: {{{{{token}}}}}; }}"
)


class _Swatch(NamedTuple):
    """One preview tile and everything needed to restyle it."""

    token: str
    label: str
    frame: QFrame
    caption: QLabel
    template: str


class FoundationWindow(QWidget):
    """Minimal window confirming that the Aashi UI foundation works.

    Args:
        environment_name: Active environment, shown so a developer can tell at
            a glance which configuration the run picked up.
        theme_manager: When supplied, the window gains the theme preview and
            follows the manager's changes. When omitted it behaves exactly as it
            did at UI-01.
        parent: Optional Qt parent.
    """

    def __init__(
        self,
        environment_name: str = "",
        theme_manager: ThemeManager | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self.setObjectName("aashiFoundationWindow")
        self.setWindowTitle(BOOTSTRAP_WINDOW_TITLE)
        self.setMinimumSize(BOOTSTRAP_WINDOW_MIN_WIDTH, BOOTSTRAP_WINDOW_MIN_HEIGHT)

        self._theme_manager = theme_manager
        self._swatches: list[_Swatch] = []
        self._status: QLabel | None = None

        self._heading = QLabel(BOOTSTRAP_WINDOW_TEXT, self)
        self._heading.setObjectName("aashiFoundationHeading")
        self._heading.setAlignment(Qt.AlignmentFlag.AlignCenter)

        details = f"v{APP_VERSION}"
        if environment_name:
            details = f"{details} — {environment_name}"
        self._details = QLabel(details, self)
        self._details.setObjectName("aashiFoundationDetails")
        self._details.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            SPACING.card_padding,
            SPACING.card_padding,
            SPACING.card_padding,
            SPACING.card_padding,
        )
        layout.setSpacing(SPACING.stack_gap)

        if theme_manager is None:
            layout.addStretch(1)
            layout.addWidget(self._heading)
            layout.addWidget(self._details)
            layout.addStretch(1)
            return

        self._heading.setFont(to_qfont(style_for(TextRole.TITLE)))
        self._details.setFont(to_qfont(style_for(TextRole.CAPTION)))
        layout.addWidget(self._heading)
        layout.addWidget(self._details)
        layout.addWidget(self._build_controls(theme_manager))
        layout.addWidget(self._build_scrollable_preview(), 1)

        self.resize(_PREVIEW_DEFAULT_WIDTH, _PREVIEW_DEFAULT_HEIGHT)

        theme_manager.theme_changed.connect(self._on_theme_changed)
        theme_manager.reduced_motion_changed.connect(self._on_theme_changed)
        self._refresh_preview()

    @property
    def heading_text(self) -> str:
        """The primary label's text. Exposed for the foundation smoke test."""
        return self._heading.text()

    @property
    def status_text(self) -> str:
        """The preview's resolved-state line; empty when there is no preview."""
        return "" if self._status is None else self._status.text()

    # -- construction -------------------------------------------------------

    def _build_controls(self, manager: ThemeManager) -> QWidget:
        """Build the temporary mode switcher and reduced-motion toggle."""
        container = QWidget(self)
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(Space.SPACE_100)

        caption = QLabel("Theme mode", container)
        caption.setFont(to_qfont(style_for(TextRole.MICRO)))
        row.addWidget(caption)

        self._mode_buttons = QButtonGroup(container)
        self._mode_buttons.setExclusive(True)
        for label, mode in _MODE_BUTTONS:
            button = QPushButton(label, container)
            button.setCheckable(True)
            button.setMinimumHeight(ControlHeight.DEFAULT)
            button.setChecked(mode is manager.mode)
            button.clicked.connect(lambda _checked, m=mode: self._select_mode(m))
            self._mode_buttons.addButton(button)
            row.addWidget(button)

        self._reduced_motion_box = QCheckBox("Force reduced motion", container)
        self._reduced_motion_box.setChecked(
            manager.motion_preference is MotionPreference.REDUCED
        )
        self._reduced_motion_box.toggled.connect(self._select_motion_preference)
        row.addSpacing(Space.SPACE_300)
        row.addWidget(self._reduced_motion_box)
        row.addStretch(1)
        return container

    def _build_scrollable_preview(self) -> QScrollArea:
        """Wrap the preview so the window stays usable at its minimum size."""
        content = QWidget()
        column = QVBoxLayout(content)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(SPACING.section_gap)

        self._status = QLabel(content)
        self._status.setObjectName("aashiPreviewStatus")
        self._status.setFont(to_qfont(style_for(TextRole.CAPTION)))
        self._status.setWordWrap(True)
        column.addWidget(self._status)

        column.addWidget(
            self._build_swatch_section(
                content, "Surfaces", _SURFACE_TOKENS, _SURFACE_TEMPLATE
            )
        )
        column.addWidget(
            self._build_swatch_section(
                content, "Text and status", _FOREGROUND_TOKENS, _FOREGROUND_TEMPLATE
            )
        )
        column.addWidget(self._build_typography_section(content))
        column.addStretch(1)

        scroll = QScrollArea(self)
        scroll.setObjectName("aashiPreviewScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        return scroll

    def _build_swatch_section(
        self,
        parent: QWidget,
        title: str,
        tokens: tuple[tuple[str, str], ...],
        template: str,
    ) -> QWidget:
        """Build one titled grid of swatches.

        Args:
            parent: Parent widget.
            title: Section heading.
            tokens: Pairs of display label and QSS token name.
            template: Stylesheet template with ``{name}`` and ``{token}`` slots,
                rendered per swatch and then fed through the QSS engine.

        Returns:
            The assembled section. Created swatches are recorded on the window
            so :meth:`_refresh_preview` can restyle them later.
        """
        section = QWidget(parent)
        column = QVBoxLayout(section)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(SPACING.stack_gap)

        heading = QLabel(title, section)
        heading.setFont(to_qfont(style_for(TextRole.SECTION)))
        column.addWidget(heading)

        grid = QGridLayout()
        grid.setSpacing(SPACING.stack_gap)
        for index, (label_text, token) in enumerate(tokens):
            frame = QFrame(section)
            frame.setObjectName(f"swatch_{token.replace('.', '_')}")
            frame.setMinimumHeight(_SWATCH_HEIGHT)
            frame.setFrameShape(QFrame.Shape.NoFrame)

            caption = QLabel(label_text, frame)
            caption.setWordWrap(True)
            caption.setFont(to_qfont(style_for(TextRole.CAPTION)))
            caption.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )

            inner = QVBoxLayout(frame)
            inner.setContentsMargins(
                SPACING.control_padding_horizontal,
                SPACING.control_padding_vertical,
                SPACING.control_padding_horizontal,
                SPACING.control_padding_vertical,
            )
            inner.addWidget(caption)

            grid.addWidget(frame, index // _SWATCH_COLUMNS, index % _SWATCH_COLUMNS)
            self._swatches.append(
                _Swatch(
                    token=token,
                    label=label_text,
                    frame=frame,
                    caption=caption,
                    template=template.format(name=frame.objectName(), token=token),
                )
            )
        column.addLayout(grid)
        return section

    def _build_typography_section(self, parent: QWidget) -> QWidget:
        """Build one specimen per text role, so the scale is visible at a glance."""
        section = QWidget(parent)
        column = QVBoxLayout(section)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(SPACING.stack_gap)

        heading = QLabel("Typography", section)
        heading.setFont(to_qfont(style_for(TextRole.SECTION)))
        column.addWidget(heading)

        for role, style in TYPOGRAPHY.items():
            specimen = QLabel(
                f"{role.value} — {style.size_px}/{style.line_height_px} "
                f"{int(style.weight)}",
                section,
            )
            specimen.setFont(to_qfont(style))
            column.addWidget(specimen)
        return section

    # -- reaction -----------------------------------------------------------

    def _select_mode(self, mode: ThemeMode) -> None:
        """Handle a mode button press."""
        if self._theme_manager is None:
            return
        self._theme_manager.set_mode(mode)
        # Refreshed unconditionally: choosing SYSTEM on an already-dark desktop
        # changes the reported state without changing the theme, so no signal
        # fires and the status line would otherwise go stale.
        self._refresh_preview()

    def _select_motion_preference(self, forced: bool) -> None:
        """Handle the reduced-motion checkbox."""
        if self._theme_manager is None:
            return
        self._theme_manager.set_motion_preference(
            MotionPreference.REDUCED if forced else MotionPreference.SYSTEM
        )
        self._refresh_preview()

    def _on_theme_changed(self, *_: object) -> None:
        """Restyle the preview when the manager reports a change."""
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        """Repaint every swatch and the status line from the active theme."""
        manager = self._theme_manager
        if manager is None or self._status is None:
            return

        theme = manager.theme
        variables = qss_variables(theme)

        for swatch in self._swatches:
            swatch.frame.setStyleSheet(render_qss(swatch.template, theme))
            swatch.caption.setText(f"{swatch.label}\n{variables[swatch.token]}")

        self._status.setText(
            f"theme: {theme.name}  ·  mode: {manager.mode.value}  ·  "
            f"resolved scheme: {manager.color_scheme.value}  ·  "
            f"high contrast: {theme.high_contrast}  ·  "
            f"reduced motion: {manager.reduced_motion}  ·  "
            f"spatial motion: {int(manager.duration(MotionRole.SPATIAL))}ms  ·  "
            f"radii: {'/'.join(str(int(r)) for r in Radius)}"
        )
