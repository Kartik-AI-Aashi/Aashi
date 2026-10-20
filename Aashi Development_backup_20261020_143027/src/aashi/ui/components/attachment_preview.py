"""Attachment preview chip shown above the composer.

A single, persistent preview of the staged attachment: a small thumbnail for
images, a document glyph for PDFs and text files, next to the filename and a
remove button. The chip stays visible while the user types and only disappears
when the message is sent or the remove button is clicked — never merely
because the input text changed.

The chip owns no attachment state itself; it only renders what
:meth:`AttachmentPreview.set_attachment` is given. The chat window keeps the
single source of truth (``AashiChatWindow._selected_file``) and clears this
chip when the attachment is sent or removed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QToolButton, QWidget

from aashi.ui.services.image_input import is_image_path
from aashi.ui.themes.definitions import Theme
from aashi.ui.themes.manager import ThemeManager
from aashi.ui.themes.qss import qss_variables
from aashi.ui.themes.qt_adapters import to_qfont
from aashi.ui.tokens.controls import ControlHeight
from aashi.ui.tokens.spacing import Space
from aashi.ui.tokens.typography import TextRole, style_for

__all__ = ["AttachmentPreview"]

_THUMB_SIZE_PX: Final[int] = ControlHeight.DEFAULT.value
"""Side of the square thumbnail box (40 px — matches the composer's controls)."""

_CLOSE_SIZE_PX: Final[int] = ControlHeight.COMPACT.value
"""Side of the remove button (32 px — the dense control size)."""


def _thumbnail(path: str) -> QPixmap | None:
    """Load ``path`` scaled to fit :data:`_THUMB_SIZE_PX`, aspect preserved."""
    from PySide6.QtGui import QImage

    image = QImage(path)
    if image.isNull():
        return None
    image = image.scaled(
        _THUMB_SIZE_PX,
        _THUMB_SIZE_PX,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    return QPixmap.fromImage(image)


class AttachmentPreview(QWidget):
    """A compact, theme-aware preview chip for the staged attachment.

    Args:
        theme_manager: The active theme manager; the chip follows it for life.
        parent: Optional Qt parent.
    """

    #: Emitted when the remove button is clicked. The owner clears its state.
    removed = Signal()

    def __init__(self, theme_manager: ThemeManager, parent=None) -> None:
        super().__init__(parent)
        self._theme_manager = theme_manager
        self.setObjectName("aashiAttachmentPreview")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Maximum)
        self.hide()

        self._thumb = QLabel()
        self._thumb.setFixedSize(_THUMB_SIZE_PX, _THUMB_SIZE_PX)
        self._thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        self._name = QLabel()
        self._name.setTextFormat(Qt.TextFormat.PlainText)
        self._name.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        self._close = QToolButton()
        self._close.setObjectName("aashiAttachmentClose")
        self._close.setText("×")
        self._close.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close.setFixedSize(_CLOSE_SIZE_PX, _CLOSE_SIZE_PX)
        self._close.clicked.connect(self.removed)

        row = QHBoxLayout(self)
        row.setContentsMargins(
            Space.SPACE_100, Space.SPACE_050, Space.SPACE_100, Space.SPACE_050
        )
        row.setSpacing(Space.SPACE_100)
        row.addWidget(self._thumb)
        row.addWidget(self._name, 1)
        row.addWidget(self._close)

        theme_manager.theme_changed.connect(self._restyle)
        self._restyle()

    @property
    def filename(self) -> str:
        """The filename currently shown on the chip."""
        return self._name.text()

    def set_attachment(self, path: str) -> None:
        """Show ``path``: a thumbnail for images, a document glyph otherwise."""
        self._name.setText(Path(path).name)
        if is_image_path(path):
            self._thumb.setText("")
            pixmap = _thumbnail(path)
            if pixmap is None:
                # An unreadable file still shows an image glyph rather than a
                # blank box; the vision path reports the read error when the
                # message is actually sent.
                self._thumb.setPixmap(QPixmap())
                self._thumb.setText("🖼")
            else:
                self._thumb.setPixmap(pixmap)
        else:
            self._thumb.setPixmap(QPixmap())
            self._thumb.setText("📄")
        self.show()

    def clear(self) -> None:
        """Reset the chip to its hidden, empty state."""
        self._thumb.setPixmap(QPixmap())
        self._thumb.setText("")
        self._name.setText("")
        self.hide()

    def _restyle(self, *_: object) -> None:
        """Regenerate the fonts and stylesheet from the active theme."""
        theme = self._theme_manager.theme
        self._name.setFont(to_qfont(style_for(TextRole.CAPTION)))
        self._thumb.setFont(to_qfont(style_for(TextRole.BODY)))
        self._close.setFont(to_qfont(style_for(TextRole.BODY)))
        self.setStyleSheet(self._build_stylesheet(theme))

    def _build_stylesheet(self, theme: Theme) -> str:
        variables = qss_variables(theme)
        stylesheet = (
            "QWidget#aashiAttachmentPreview {\n"
            f"  background-color: {variables['color.surface.nested']};\n"
            f"  border: {variables['border.hairline']} solid "
            f"{variables['color.border']};\n"
            f"  border-radius: {variables['radius.large']};\n"
            "}\n"
            "QToolButton#aashiAttachmentClose {\n"
            "  background-color: transparent;\n"
            "  border: none;\n"
            f"  color: {variables['color.text.tertiary']};\n"
            f"  border-radius: {_CLOSE_SIZE_PX // 2}px;\n"
            "}\n"
            "QToolButton#aashiAttachmentClose:hover {\n"
            f"  background-color: {variables['color.accent.tintHover']};\n"
            f"  color: {variables['color.text']};\n"
            "}\n"
            "QToolButton#aashiAttachmentClose:pressed {\n"
            f"  background-color: {variables['color.accent.tint']};\n"
            "}\n"
        )
        if theme.high_contrast:
            # High contrast collapses the chip onto its surface, so a solid
            # outline is what separates it from the window around it.
            stylesheet += (
                "QWidget#aashiAttachmentPreview {\n"
                f"  border-color: {variables['color.border.strong']};\n"
                "}\n"
            )
        return stylesheet
