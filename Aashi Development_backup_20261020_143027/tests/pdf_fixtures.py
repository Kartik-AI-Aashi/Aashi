"""Test fixtures: minimal selectable-text PDFs.

No PDF-writing library is installed, so tests hand-build small PDFs that
``pypdf`` can read. Each PDF is a valid single- or multi-page document whose
pages draw Helvetica text, which ``pypdf``'s ``extract_text`` recovers with
line breaks intact — exactly the normal selectable-text case the extractor
must handle.
"""

from __future__ import annotations


def make_pdf(pages: list[str]) -> bytes:
    """Build a minimal PDF with one text page per entry in ``pages``.

    Args:
        pages: One plain-text string per page; ``\\n`` inside a string becomes
            a line break on that page.

    Returns:
        The PDF bytes.
    """
    n = len(pages)
    font_obj = 3 + 2 * n
    catalog = b"<< /Type /Catalog /Pages 2 0 R >>"
    kids = b" ".join(f"{i} 0 R".encode() for i in range(3, 3 + n))
    pages_obj = (
        b"<< /Type /Pages /Kids [" + kids + b"] /Count " + str(n).encode() + b" >>"
    )
    page_objs: list[bytes] = []
    content_objs: list[bytes] = []
    for i, page_text in enumerate(pages):
        stream = _content_stream(page_text)
        content_objs.append(
            b"<< /Length "
            + str(len(stream)).encode()
            + b" >>\nstream\n"
            + stream
            + b"\nendstream"
        )
        page_objs.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 "
            + str(font_obj).encode()
            + b" 0 R >> >> /Contents "
            + str(3 + n + i).encode()
            + b" 0 R >>"
        )
    font = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"

    body = [catalog, pages_obj] + page_objs + content_objs + [font]
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, obj in enumerate(body, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + obj + b"\nendobj\n"
    xref_pos = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(body) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += (
        b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
        % (len(body) + 1, xref_pos)
    )
    return bytes(out)


def _content_stream(text: str) -> bytes:
    """Build a content stream drawing ``text`` as one line per ``\\n`` part."""
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    out = bytearray(b"BT\n/F1 12 Tf\n12 TL\n72 720 Td\n")
    for line in escaped.split("\n"):
        out += b"(" + line.encode("latin-1") + b") Tj\nT*\n"
    out += b"ET\n"
    return bytes(out)
