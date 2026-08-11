"""Local document reading and extraction for the file-attach feature.

A remote AI model can never reach the user's filesystem, so an attached PDF or
Word document must be read *here* first and the extracted content handed to the
model as plain text. This module does that extraction — it is Qt-free and
blocking, so the chat window runs it on a worker thread.

Supported inputs:

* ``.pdf``  — text extracted page by page with ``pypdf``, in page order, each
  page labelled ``[Page N]`` so the model can answer page-specific questions.
  A PDF with no extractable text (a scan) is detected and reported, not
  silently passed through as empty content.
* ``.docx`` — paragraphs, headings, bullet/numbered lists and tables extracted
  in document order via ``python-docx``. Tables become a ``|``-separated text
  block (header row, then a dash rule, then the data rows) so they are never
  silently discarded.
* ``.doc``  — recognised but unsupported without an external converter
  (Word/LibreOffice), so it raises :class:`UnsupportedDocumentError` instead of
  pretending to read it.

Large documents are capped to a character budget (:data:`MAX_DOCUMENT_CHARS`)
so a huge file is never pushed wholesale into the model. The cap keeps whole
pages/paragraph blocks and marks the prompt as truncated, so the model answers
only from the content it was actually shown.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

from pypdf import PdfReader

__all__ = [
    "DOCUMENT_EXTS",
    "MAX_DOCUMENT_CHARS",
    "DocumentInputError",
    "ScannedDocumentError",
    "UnsupportedDocumentError",
    "build_document_prompt",
    "cap_document_text",
    "extract_docx_text",
    "extract_document",
    "extract_pdf_text",
    "is_document_path",
]

DOCUMENT_EXTS: Final[frozenset[str]] = frozenset({".pdf", ".docx", ".doc"})
"""File extensions routed to the document-understanding pipeline."""

MAX_DOCUMENT_CHARS: Final[int] = 60_000
"""Maximum characters of document content sent with one request.

Roughly 15k tokens — comfortably inside the model input limits. Documents
larger than this are truncated at a page/paragraph boundary (never mid-page)
and the prompt tells the model the document was longer than what was shown.
"""

# Group of 2+ newlines splits the extraction into page/paragraph blocks. For a
# PDF each block starts with its ``[Page N]`` marker; for a DOCX a block is a
# paragraph group. The cap truncates whole blocks so the model never sees a
# half page.
_BLOCK_SEPARATOR_RE: Final[re.Pattern[str]] = re.compile(r"\n{2,}")

_PAGE_MARKER_RE: Final[re.Pattern[str]] = re.compile(r"\[Page \d+\]")

_HEADING_LEVEL_RE: Final[re.Pattern[str]] = re.compile(r"(\d+)")


class DocumentInputError(Exception):
    """The attached document could not be read or extracted."""


class ScannedDocumentError(DocumentInputError):
    """The PDF is image-based and contains no extractable text.

    Detected instead of pretending the scan was read: a scanned PDF must go
    through OCR/vision, which is not part of the text-extraction path.
    """


class UnsupportedDocumentError(DocumentInputError):
    """The attached file's format is not supported for extraction."""


def is_document_path(path: str) -> bool:
    """Return ``True`` when ``path``'s extension names a document format."""
    return Path(path).suffix.lower() in DOCUMENT_EXTS


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def extract_document(path: str) -> str:
    """Extract ``path`` into model-readable text, dispatching by extension.

    Args:
        path: The attached document's path.

    Returns:
        The extracted document content.

    Raises:
        ScannedDocumentError: The PDF has no extractable text.
        UnsupportedDocumentError: The format is not supported (e.g. ``.doc``).
        DocumentInputError: The file could not be read or extracted.
    """
    suffix = Path(path).suffix.lower()
    if suffix == ".pdf":
        return extract_pdf_text(path)
    if suffix == ".docx":
        return extract_docx_text(path)
    if suffix == ".doc":
        raise UnsupportedDocumentError(
            "Legacy .doc files need an external converter (Word/LibreOffice), "
            "which Aashi does not depend on."
        )
    raise UnsupportedDocumentError(f"Unsupported document format: {suffix or '(none)'}")


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


def extract_pdf_text(path: str) -> str:
    """Extract every page's text from ``path`` in page order.

    Each page is labelled ``[Page N]`` so the model can refer to pages
    directly (e.g. "the topic on page 2"). A PDF whose pages yield no text is
    treated as a scan: :class:`ScannedDocumentError` is raised rather than
    returning empty content.

    Raises:
        ScannedDocumentError: No page produced any text.
        DocumentInputError: The file is not a readable PDF.
    """
    try:
        reader = PdfReader(str(path))
    except Exception as exc:
        raise DocumentInputError(f"Could not read PDF: {exc}") from exc

    pages: list[tuple[int, str]] = []
    for index, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            # A single broken page should not sink the whole document; treat it
            # as having no extractable text and move on.
            text = ""
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        pages.append((index, text))

    if all(not text for _, text in pages):
        raise ScannedDocumentError(
            "PDF contains no extractable text (likely scanned images)."
        )

    labelled = [f"[Page {index}]\n{text}" for index, text in pages if text]
    return "\n\n".join(labelled)


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------


def extract_docx_text(path: str) -> str:
    """Extract a ``.docx`` as text, preserving the document's logical order.

    The body is walked in document order so a heading, its paragraph, a bullet
    list and a table are emitted exactly as they appear. Paragraphs keep their
    text; headings are marked with ``#``/``##``; list bullets with ``• `` and
    numbered items with a running ``1.``/``2.`` counter; tables become a
    ``|``-separated block with a dash rule under the header row.

    Raises:
        DocumentInputError: The file is not a readable ``.docx``.
    """
    try:
        from docx import Document
        from docx.oxml.ns import qn
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        document = Document(str(path))
        body = document.element.body
    except Exception as exc:
        raise DocumentInputError(f"Could not read DOCX: {exc}") from exc

    parts: list[str] = []
    number_counter = 0

    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            paragraph = Paragraph(child, document)
            line, number_counter = _format_docx_paragraph(paragraph, number_counter)
            if line:
                parts.append(line)
        elif child.tag == qn("w:tbl"):
            number_counter = 0
            table = _format_docx_table(Table(child, document))
            if table:
                parts.append(table)

    return "\n\n".join(parts)


def _format_docx_paragraph(paragraph, number_counter: int) -> tuple[str, int]:
    """Format one DOCX paragraph according to its style, returning (line, counter).

    ``number_counter`` is threaded through consecutive ``List Number``
    paragraphs so a numbered list reads ``1.``/``2.``/``3.``; any other block
    resets it.
    """
    text = paragraph.text.strip()
    if not text:
        return "", 0

    style_name = ""
    if paragraph.style is not None:
        style_name = paragraph.style.name or ""

    if style_name.startswith("Heading"):
        match = _HEADING_LEVEL_RE.search(style_name)
        level = int(match.group(1)) if match else 1
        return f"{'#' * max(level, 1)} {text}", 0

    if "Bullet" in style_name:
        return f"• {text}", 0

    if "Number" in style_name:
        number_counter += 1
        return f"{number_counter}. {text}", number_counter

    return text, 0


def _format_docx_table(table) -> str:
    """Render a DOCX table as a model-readable ``|``-separated block."""
    rows: list[list[str]] = []
    for row in table.rows:
        cells = [
            cell.text.strip().replace("\n", " ") if cell.text else ""
            for cell in row.cells
        ]
        rows.append(cells)

    if not rows:
        return ""

    lines = ["Table:"]
    lines.append(" | ".join(rows[0]))
    lines.append(" | ".join("-" * max(len(cell), 1) for cell in rows[0]))
    for row in rows[1:]:
        lines.append(" | ".join(row))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Large-document cap
# ---------------------------------------------------------------------------


def cap_document_text(
    text: str, limit: int = MAX_DOCUMENT_CHARS
) -> tuple[str, bool]:
    """Cap ``text`` to ``limit`` characters at a page/paragraph boundary.

    The text is split into blocks (each ``[Page N]`` block for a PDF, a
    paragraph group for a DOCX) and whole blocks are kept while they fit, so
    pages are never cut mid-way when they fit. If a single block overflows the
    budget on its own (a pathological oversized page) it is hard-cut to the
    limit, so the model is never sent more than ``limit`` characters.

    Returns:
        A ``(capped_text, truncated)`` pair; ``truncated`` is ``True`` when
        any content was dropped.
    """
    if len(text) <= limit:
        return text, False

    blocks = [block for block in _BLOCK_SEPARATOR_RE.split(text) if block.strip()]
    included: list[str] = []
    used = 0
    for block in blocks:
        cost = len(block) + 2  # +2 for the \n\n separator on rejoin
        if included and used + cost > limit:
            break
        included.append(block)
        used += cost

    capped = "\n\n".join(included)
    if len(capped) > limit:
        capped = capped[:limit]
    return capped, True


# ---------------------------------------------------------------------------
# Prompt composition
# ---------------------------------------------------------------------------


def build_document_prompt(
    question: str,
    doc_text: str,
    filename: str,
    *,
    truncated: bool = False,
) -> str:
    """Compose the AI request for an attached document.

    The user's question and the extracted document are clearly separated, and
    the model is instructed to answer only from the document content — never
    to invent or substitute general knowledge for missing content. This string
    is the *message* sent to the model; it is never shown to the user.

    Args:
        question: The user's question about the document.
        doc_text: The extracted document content (already capped if large).
        filename: The attached file's name, shown as the document label.
        truncated: Whether ``doc_text`` was capped and the document continues
            past the provided content.

    Returns:
        The composed user message.
    """
    parts = [
        "USER QUESTION:",
        question,
        "",
        f'ATTACHED DOCUMENT: "{filename}"',
        '"""',
        doc_text.strip(),
        '"""',
    ]
    if truncated:
        parts.extend(
            [
                "",
                "[The document was longer than could be included. Only the "
                "portion above was provided.]",
            ]
        )
    parts.extend(
        [
            "",
            "Answer the user's question using ONLY the document content above. "
            "Do not invent or guess information that is not in the document. "
            "If the document does not contain the information, say that it "
            "could not be found in the document.",
        ]
    )
    return "\n".join(parts)
