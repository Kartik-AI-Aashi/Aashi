"""Verify image encoding for vision-capable model requests.

Covers extension/MIME detection, data-URI generation with a MIME that matches
the encoded bytes, downscaling of oversized images with preserved aspect ratio,
and graceful failure on unreadable files.
"""

from __future__ import annotations

import base64

import pytest

pytest.importorskip("pytestqt", reason="pytest-qt is required for GUI tests")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402

from aashi.ui.services.image_input import (  # noqa: E402
    IMAGE_EXTS,
    MAX_IMAGE_SIDE_PX,
    ImageInputError,
    encode_image_data_uri,
    is_image_path,
    mime_type_for,
)


def _save(path, fmt: str, width: int = 64, height: int = 48) -> None:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.blue)
    assert image.save(str(path), fmt)


def _decode(uri: str) -> QImage:
    raw = base64.b64decode(uri.split(",", 1)[1])
    image = QImage()
    image.loadFromData(raw)
    return image


# ── Extension and MIME detection ─────────────────────────────────────────────


def test_supported_extensions_include_webp_and_gif() -> None:
    assert {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"} <= IMAGE_EXTS


def test_is_image_path_recognises_supported_extensions_case_insensitively(tmp_path) -> None:
    assert is_image_path(str(tmp_path / "a.PNG"))
    assert is_image_path(str(tmp_path / "a.webp"))
    assert not is_image_path(str(tmp_path / "a.txt"))
    assert not is_image_path(str(tmp_path / "notes.pdf"))


def test_mime_type_detected_per_extension(tmp_path) -> None:
    assert mime_type_for(str(tmp_path / "x.png")) == "image/png"
    assert mime_type_for(str(tmp_path / "x.jpg")) == "image/jpeg"
    assert mime_type_for(str(tmp_path / "x.jpeg")) == "image/jpeg"
    assert mime_type_for(str(tmp_path / "x.webp")) == "image/webp"
    assert mime_type_for(str(tmp_path / "x.gif")) == "image/gif"
    assert mime_type_for(str(tmp_path / "x.txt")) == "application/octet-stream"


# ── Data-URI encoding ────────────────────────────────────────────────────────


def test_encode_png_produces_png_data_uri(tmp_path) -> None:
    png = tmp_path / "photo.png"
    _save(png, "PNG")

    uri = encode_image_data_uri(str(png))

    assert uri.startswith("data:image/png;base64,")
    assert base64.b64decode(uri.split(",", 1)[1]).startswith(b"\x89PNG")


def test_encode_jpeg_produces_jpeg_data_uri(tmp_path) -> None:
    jpg = tmp_path / "photo.jpg"
    _save(jpg, "JPEG")

    uri = encode_image_data_uri(str(jpg))

    assert uri.startswith("data:image/jpeg;base64,")
    assert base64.b64decode(uri.split(",", 1)[1]).startswith(b"\xff\xd8")


def test_gif_is_sent_as_png_still_frame(tmp_path) -> None:
    gif = tmp_path / "anim.gif"
    _save(gif, "PNG")  # file bytes are a still; only the extension says GIF

    uri = encode_image_data_uri(str(gif))

    assert uri.startswith("data:image/png;base64,")


def test_normal_image_is_not_resized(tmp_path) -> None:
    img = tmp_path / "small.png"
    _save(img, "PNG", width=300, height=200)

    decoded = _decode(encode_image_data_uri(str(img)))

    assert decoded.width() == 300
    assert decoded.height() == 200


def test_large_image_is_downscaled_preserving_aspect(tmp_path) -> None:
    img = tmp_path / "big.png"
    _save(img, "PNG", width=4000, height=1000)

    decoded = _decode(encode_image_data_uri(str(img)))

    assert decoded.width() <= MAX_IMAGE_SIDE_PX
    ratio = decoded.width() / decoded.height()
    assert abs(ratio - 4.0) < 0.05  # 4000:1000 aspect kept


# ── Failure modes ────────────────────────────────────────────────────────────


def test_missing_file_raises(tmp_path) -> None:
    with pytest.raises(ImageInputError):
        encode_image_data_uri(str(tmp_path / "missing.png"))


def test_corrupt_image_raises(tmp_path) -> None:
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not actually a png")

    with pytest.raises(ImageInputError):
        encode_image_data_uri(str(bad))


def test_non_image_file_raises(tmp_path) -> None:
    txt = tmp_path / "notes.txt"
    txt.write_text("plain text", encoding="utf-8")

    with pytest.raises(ImageInputError):
        encode_image_data_uri(str(txt))
