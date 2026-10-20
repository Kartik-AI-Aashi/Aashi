"""Verify the attachment preview chip above the composer.

Covers the hidden-by-default state, image thumbnails vs. document glyphs,
clearing, the remove button's ``removed`` signal, and re-styling on theme
change.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pytestqt", reason="pytest-qt is required for GUI tests")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QToolButton  # noqa: E402

from aashi.ui.components.attachment_preview import AttachmentPreview  # noqa: E402
from aashi.ui.themes.manager import ThemeManager  # noqa: E402
from aashi.ui.themes.mode import ColorScheme, ThemeMode  # noqa: E402
from aashi.ui.themes.system import SystemPreferences  # noqa: E402


def _manager() -> ThemeManager:
    return ThemeManager(system_reader=lambda: SystemPreferences(
        color_scheme=ColorScheme.DARK,
        high_contrast=False,
        reduced_motion=False,
    ))


def _save_png(path, width: int = 120, height: int = 80) -> None:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.red)
    assert image.save(str(path), "PNG")


def test_hidden_by_default(qtbot) -> None:
    preview = AttachmentPreview(_manager())
    qtbot.addWidget(preview)

    assert preview.isHidden()
    assert preview.filename == ""


def test_image_attachment_shows_thumbnail_and_name(qtbot, tmp_path) -> None:
    png = tmp_path / "photo.png"
    _save_png(png)
    preview = AttachmentPreview(_manager())
    qtbot.addWidget(preview)

    preview.set_attachment(str(png))

    assert not preview.isHidden()
    assert preview.filename == "photo.png"
    assert not preview._thumb.pixmap().isNull()


def test_document_attachment_shows_glyph_and_name(qtbot, tmp_path) -> None:
    doc = tmp_path / "Summer.pdf"
    doc.write_bytes(b"%PDF-1.4 dummy")
    preview = AttachmentPreview(_manager())
    qtbot.addWidget(preview)

    preview.set_attachment(str(doc))

    assert not preview.isHidden()
    assert preview.filename == "Summer.pdf"
    assert preview._thumb.text() == "📄"
    assert preview._thumb.pixmap().isNull()


def test_unreadable_image_still_shows_glyph(qtbot, tmp_path) -> None:
    bad = tmp_path / "broken.png"
    bad.write_bytes(b"not an image")
    preview = AttachmentPreview(_manager())
    qtbot.addWidget(preview)

    preview.set_attachment(str(bad))

    assert not preview.isHidden()
    assert preview.filename == "broken.png"
    assert preview._thumb.pixmap().isNull()
    assert preview._thumb.text() == "🖼"


def test_clear_resets_the_chip(qtbot, tmp_path) -> None:
    doc = tmp_path / "notes.txt"
    doc.write_text("hi", encoding="utf-8")
    preview = AttachmentPreview(_manager())
    qtbot.addWidget(preview)
    preview.set_attachment(str(doc))

    preview.clear()

    assert preview.isHidden()
    assert preview.filename == ""


def test_remove_button_emits_removed(qtbot, tmp_path) -> None:
    doc = tmp_path / "notes.txt"
    doc.write_text("hi", encoding="utf-8")
    preview = AttachmentPreview(_manager())
    qtbot.addWidget(preview)
    preview.set_attachment(str(doc))

    with qtbot.waitSignal(preview.removed):
        close = preview.findChild(QToolButton)
        close.click()


def test_restyles_on_theme_change(qtbot) -> None:
    manager = _manager()
    preview = AttachmentPreview(manager)
    qtbot.addWidget(preview)
    assert preview.styleSheet()

    manager.set_mode(ThemeMode.LIGHT)

    assert preview.styleSheet()
    assert manager.theme.palette.text.tertiary.css in preview.styleSheet()
