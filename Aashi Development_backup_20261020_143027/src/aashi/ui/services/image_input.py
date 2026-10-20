"""Image reading and encoding for vision-capable model requests.

The chat window hands an attached image to :func:`encode_image_data_uri` on a
worker thread, and the resulting ``data:`` URI is sent to the vision model as
an ``image_url`` content part. Reading, resizing and encoding all happen
locally — a remote model can never reach the user's filesystem, and the raw
local path is never transmitted.

Supported inputs: PNG, JPEG, WEBP, GIF (sent as a still first frame) and BMP.
A file is never mislabelled: the MIME type in the returned URI always matches
the bytes that were actually encoded, not merely the original extension.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Final

from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage

__all__ = [
    "IMAGE_EXTS",
    "IMAGE_MIME_BY_EXT",
    "ImageInputError",
    "MAX_IMAGE_SIDE_PX",
    "encode_image_data_uri",
    "is_image_path",
    "mime_type_for",
]

IMAGE_EXTS: Final[frozenset[str]] = frozenset(
    {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
)
"""File extensions treated as images."""

IMAGE_MIME_BY_EXT: Final[dict[str, str]] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}
"""MIME type per supported extension."""

MAX_IMAGE_SIDE_PX: Final[int] = 2048
"""Longest edge above which an image is downscaled before transport.

2048 px preserves ample detail for visual understanding while keeping the
encoded payload comfortably inside model input limits; normal images are never
touched.
"""

_MIME_BY_OUTPUT_FORMAT: Final[dict[str, str]] = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "WEBP": "image/webp",
}
"""Output format name → MIME type for the bytes actually encoded."""

_FORMAT_BY_EXT: Final[dict[str, str]] = {
    ".png": "PNG",
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".webp": "WEBP",
    ".gif": "PNG",  # animated GIFs are sent as a still first frame
    ".bmp": "PNG",  # BMP re-encoded as PNG for a far smaller payload
}
"""Preferred output format per input extension."""


class ImageInputError(Exception):
    """The attached file could not be read or encoded as an image."""


def is_image_path(path: str) -> bool:
    """Return ``True`` when ``path``'s extension names a supported image type."""
    return Path(path).suffix.lower() in IMAGE_EXTS


def mime_type_for(path: str) -> str:
    """Return the MIME type implied by ``path``'s extension.

    Used to label the preview and to pick an output format; the transport MIME
    (see :func:`encode_image_data_uri`) is always matched to the encoded bytes.
    """
    return IMAGE_MIME_BY_EXT.get(Path(path).suffix.lower(), "application/octet-stream")


def _encode_bytes(image: QImage, output_format: str) -> bytes | None:
    """Encode ``image`` to ``output_format`` bytes, or ``None`` if unsupported."""
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, output_format):
        return None
    return bytes(buffer.data())


def encode_image_data_uri(path: str) -> str:
    """Encode the image at ``path`` as a ``data:`` URI for a vision request.

    The image is decoded locally, downscaled (aspect preserved) only when its
    longest edge exceeds :data:`MAX_IMAGE_SIDE_PX`, re-encoded and base64
    wrapped. GIF and BMP are sent as PNG; WEBP stays WEBP when the Qt build can
    encode it and otherwise falls back to PNG, so a readable image is never
    lost just because an encoder is missing.

    Returns:
        A ``data:<mime>;base64,...`` URI whose MIME matches the encoded bytes.

    Raises:
        ImageInputError: If the file cannot be decoded or re-encoded.
    """
    image = QImage(path)
    if image.isNull():
        raise ImageInputError(f"Could not read image: {path}")

    if max(image.width(), image.height()) > MAX_IMAGE_SIDE_PX:
        image = image.scaled(
            MAX_IMAGE_SIDE_PX,
            MAX_IMAGE_SIDE_PX,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    output_format = _FORMAT_BY_EXT.get(Path(path).suffix.lower(), "PNG")
    data = _encode_bytes(image, output_format)
    if data is None and output_format != "PNG":
        output_format = "PNG"
        data = _encode_bytes(image, output_format)
    if data is None:
        raise ImageInputError(f"Could not encode image: {path}")

    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{_MIME_BY_OUTPUT_FORMAT[output_format]};base64,{encoded}"
