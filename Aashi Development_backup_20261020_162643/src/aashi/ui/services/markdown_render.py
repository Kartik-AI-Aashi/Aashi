"""Markdown → HTML for the chat bubble's rich-text ``QLabel``.

``QLabel`` in ``Qt.RichText`` mode treats its text as HTML, and in HTML every
run of whitespace — including newlines — collapses to one space. Plain
``\\n`` / ``\\n\\n`` therefore never produce a line or paragraph break, and
Markdown markers (``**bold**``, ``### heading``, ``1.`` lists) stay as raw
symbols. That is what turned every answer into one dense paragraph.

:func:`render_markdown` converts the Markdown that models write into explicit
block HTML that survives the label: ``<p>`` paragraphs, headings, nested
``<ul>`` / ``<ol>`` lists, tables, quotes, rules, ``<pre>`` code blocks and
inline bold / italic / code / links. All text is HTML-escaped first, so
nothing a model (or user) writes can inject markup.

:func:`tidy_reply` is the companion *repair* step for small models that return
a wall of text: it moves inline "1. … 2. …" lists and inline "### headings"
onto their own lines and breaks very long paragraphs. It only ever changes
whitespace, never wording.

Both functions are Qt-free and unit-tested in pure Python.
"""

from __future__ import annotations

import html as _html
import re
from typing import Final

__all__ = ["render_markdown", "tidy_reply"]

# -- block patterns ---------------------------------------------------------------

_FENCE_OPEN_RE: Final = re.compile(r"^\s*```[\w+#.-]*\s*$")
_FENCE_RE: Final = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)
_HEADING_RE: Final = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_HR_RE: Final = re.compile(r"^\s{0,3}([-*_])(?:\s*\1){2,}\s*$")
_LIST_RE: Final = re.compile(r"^(\s*)([-*+•]|\d{1,3}[.)])\s+(.*)$")
_QUOTE_RE: Final = re.compile(r"^\s{0,3}>\s?(.*)$")
_TABLE_SEP_RE: Final = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")

# -- styling (neutral values that read on both the light and dark theme) --------------

_GAP_PX: Final = 10
_RULE_COLOUR: Final = "#8a8f9c"
_CODE_STYLE: Final = (
    "font-family:'Cascadia Mono','Consolas','Courier New',monospace;"
    "background-color:rgba(138,143,156,0.28);"
)
_HEADING_SIZES: Final = {1: 20, 2: 18, 3: 16, 4: 15, 5: 15, 6: 15}
_HEADING_GAP_PX: Final = 16

_HEADING_MARGIN: Final = "\x01H\x01"
_MARGIN: Final = "\x01M\x01"
"""Placeholder for a block's top margin: 0 for the first block, ``_GAP_PX`` after.

Control characters, so they can never collide with text or code (``{M}`` could).
Control characters are stripped from the input before rendering.
"""


def _inline(text: str) -> str:
    """Render inline Markdown (code, links, bold, italic, strike) to HTML."""
    codes: list[str] = []

    def stash(match: re.Match[str]) -> str:
        codes.append(match.group(1))
        return f"\x00{len(codes) - 1}\x00"

    text = re.sub(r"`([^`\n]+)`", stash, text)
    text = _html.escape(text)
    text = re.sub(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)", r'<a href="\2">\1</a>', text)
    text = re.sub(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<![\w_])__(?=\S)(.+?)(?<=\S)__(?![\w_])", r"<b>\1</b>", text)
    text = re.sub(r"(?<![\w*])\*(?=[^\s*])(.+?)(?<=[^\s*])\*(?![\w*])", r"<i>\1</i>", text)
    text = re.sub(r"(?<![\w_])_(?=[^\s_])(.+?)(?<=[^\s_])_(?![\w_])", r"<i>\1</i>", text)
    text = re.sub(r"~~(?=\S)(.+?)(?<=\S)~~", r"<s>\1</s>", text)
    return re.sub(
        r"\x00(\d+)\x00",
        lambda m: f'<code style="{_CODE_STYLE}">{_html.escape(codes[int(m.group(1))])}</code>',
        text,
    )


def _code_panel(pre: str) -> str:
    """Wrap a ``<pre>`` in a one-cell table so it gets a subtle background panel."""
    return (
        f'<table cellpadding="9" cellspacing="0" style="margin-top:{_MARGIN}px;">'
        f'<tr><td style="background-color:rgba(138,143,156,0.20);">{pre}</td></tr></table>'
    )


def _is_block_start(line: str) -> bool:
    """True if ``line`` begins a non-paragraph block (so a paragraph ends before it)."""
    return bool(
        _FENCE_OPEN_RE.match(line)
        or _HEADING_RE.match(line)
        or _HR_RE.match(line)
        or _LIST_RE.match(line)
        or _QUOTE_RE.match(line)
    )


def _render_list(items: list[tuple[int, bool, int, str]]) -> str:
    """Render consecutive list items (indent, ordered, number, text) with nesting."""
    out: list[str] = []
    stack: list[tuple[int, str]] = []  # (indent, tag) of each open list
    last_number: dict[int, int] = {}  # indent -> last ordered number seen there
    nested = "margin-top:2px;margin-bottom:2px;"
    for indent, ordered, number, text in items:
        tag = "ol" if ordered else "ul"
        while stack and indent < stack[-1][0]:
            out.append(f"</li></{stack.pop()[1]}>")
        # "1." right after "3." is a new list, not item 4 of the old one.
        if ordered and number == 1 and last_number.get(indent, 0) > 1:
            if stack and stack[-1][0] == indent and stack[-1][1] == "ol":
                out.append(f"</li></{stack.pop()[1]}>")
        if ordered:
            last_number[indent] = number
        for deeper in [k for k in last_number if k > indent]:
            del last_number[deeper]
        if stack and indent == stack[-1][0]:
            out.append("</li>")
            if stack[-1][1] != tag:
                out.append(f"</{stack.pop()[1]}>")
        if not stack or indent > stack[-1][0]:
            top = not stack
            style = f"margin-top:{_MARGIN}px;margin-bottom:0px;" if top else nested
            start = f' start="{number}"' if ordered and number != 1 else ""
            out.append(f'<{tag}{start} style="{style}">')
            stack.append((indent, tag))
        out.append(f'<li style="margin-bottom:3px;">{_inline(text)}')
    while stack:
        out.append(f"</li></{stack.pop()[1]}>")
    return "".join(out)


def _split_row(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _render_table(header: list[str], rows: list[list[str]]) -> str:
    attrs = (
        f'cellpadding="6" cellspacing="0" border="1" '
        f'style="border-color:{_RULE_COLOUR};margin-top:{_MARGIN}px;"'
    )
    out = [f"<table {attrs}><tr>"]
    out.extend(f"<th>{_inline(c)}</th>" for c in header)
    out.append("</tr>")
    for row in rows:
        out.append("<tr>")
        padded = (row + [""] * len(header))[: len(header)]
        out.extend(f"<td>{_inline(c)}</td>" for c in padded)
        out.append("</tr>")
    out.append("</table>")
    return "".join(out)


def render_markdown(text: str) -> str:
    """Convert Markdown *text* to HTML for a rich-text ``QLabel``.

    Handles paragraphs (single newlines become ``<br>``), ``#`` headings,
    bullet and numbered lists (nested by indentation), ``>`` quotes, ``---``
    rules, pipe tables, fenced code blocks (``<pre>``, whitespace preserved —
    needed for flowcharts) and inline ``**bold**`` / ``*italic*`` /
    `` `code` `` / ``[links](https://…)``. An unterminated code fence runs to
    the end, so a half-streamed reply still renders sensibly.

    Everything is HTML-escaped; a text that is a single plain paragraph (or a
    single code block) comes back without a ``<p>`` wrapper.

    Args:
        text: Raw assistant reply.

    Returns:
        An HTML string ready for ``QLabel.setText()``.
    """
    if not text or not text.strip():
        return ""
    text = re.sub(r"[\x00\x01]", "", text)  # reserved as internal placeholders
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[tuple[str, str]] = []  # (kind, html)
    i, n = 0, len(lines)

    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1
            continue

        if _FENCE_OPEN_RE.match(line):
            code: list[str] = []
            i += 1
            while i < n and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1  # skip the closing fence (or run off the end)
            body = _html.escape("\n".join(code).rstrip("\n"))
            blocks.append(("pre", f"<pre>{body}</pre>"))
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            size = _HEADING_SIZES[len(heading.group(1))]
            blocks.append((
                "h",
                f'<p style="margin-top:{_HEADING_MARGIN}px;margin-bottom:0px;">'
                f'<span style="font-size:{size}px;font-weight:600;">'
                f"{_inline(heading.group(2))}</span></p>",
            ))
            i += 1
            continue

        if _HR_RE.match(line):
            blocks.append(("hr", "<hr>"))
            i += 1
            continue

        if "|" in line and i + 1 < n and "-" in lines[i + 1] and _TABLE_SEP_RE.match(lines[i + 1]):
            header = _split_row(line)
            i += 2
            rows: list[list[str]] = []
            while i < n and "|" in lines[i] and lines[i].strip():
                rows.append(_split_row(lines[i]))
                i += 1
            blocks.append(("table", _render_table(header, rows)))
            continue

        if _QUOTE_RE.match(line):
            quoted: list[str] = []
            while i < n:
                q = _QUOTE_RE.match(lines[i])
                if not q:
                    break
                quoted.append(q.group(1))
                i += 1
            body = "<br>".join(_inline(q) for q in quoted)
            blocks.append((
                "quote",
                f'<p style="margin-top:{_MARGIN}px;margin-bottom:0px;margin-left:14px;'
                f'font-style:italic;">{body}</p>',
            ))
            continue

        if _LIST_RE.match(line):
            items: list[tuple[int, bool, int, str]] = []
            while i < n:
                match = _LIST_RE.match(lines[i])
                if match:
                    indent = len(match.group(1).expandtabs(4))
                    marker = match.group(2)
                    ordered = marker[0].isdigit()
                    number = int(marker[:-1]) if ordered else 0
                    items.append((indent, ordered, number, match.group(3)))
                    i += 1
                elif not lines[i].strip():
                    # A blank line keeps the list going only if another item follows.
                    j = i + 1
                    while j < n and not lines[j].strip():
                        j += 1
                    if j < n and _LIST_RE.match(lines[j]):
                        i = j
                    else:
                        break
                elif items and lines[i].startswith((" ", "\t")) and not _is_block_start(lines[i]):
                    ind, ordered, number, prev = items[-1]  # wrapped continuation line
                    items[-1] = (ind, ordered, number, f"{prev} {lines[i].strip()}")
                    i += 1
                else:
                    break
            blocks.append(("list", _render_list(items)))
            continue

        para: list[str] = []
        while i < n and lines[i].strip() and not (para and _is_block_start(lines[i])):
            para.append(lines[i].strip())
            i += 1
        blocks.append(("p", "<br>".join(_inline(p) for p in para)))

    if len(blocks) == 1 and blocks[0][0] in {"p", "pre"}:
        return blocks[0][1]  # a lone paragraph / code block needs no wrapper

    out: list[str] = []
    for index, (kind, body) in enumerate(blocks):
        if kind == "p":
            body = f'<p style="margin-top:{_MARGIN}px;margin-bottom:0px;">{body}</p>'
        elif kind == "pre":
            body = _code_panel(body)
        body = body.replace(_HEADING_MARGIN, "0" if index == 0 else str(_HEADING_GAP_PX))
        out.append(body.replace(_MARGIN, "0" if index == 0 else str(_GAP_PX)))
    return "".join(out)


# ---------------------------------------------------------------------------------
# Repair for walls of text
# ---------------------------------------------------------------------------------

_INLINE_NUMBER_RE: Final = re.compile(r"(?:(?<=\s)|^)(\d{1,2})[.)]\s+(?=\S)")
_INLINE_HEADING_RE: Final = re.compile(r"(?<=\S)\s+(#{2,4})\s+(?=\S)")
_INLINE_BULLET_RE: Final = re.compile(r"\s+•\s+")
_AFTER_COLON_DASH_RE: Final = re.compile(r"(?<=[:.!?])\s+-\s+(?=[A-Z0-9*])")
_LABEL_AFTER_SENTENCE_RE: Final = re.compile(r"(?<=[.!?])\s+(?=\*\*[^*\n]{1,40}\*\*\s*:)")
_SENTENCE_END_RE: Final = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"“*(])")
_LONG_PARAGRAPH_CHARS: Final = 320
_CHUNK_CHARS: Final = 240


def _split_inline_numbers(line: str) -> str:
    """Put "1. a 2. b 3. c" items on separate lines when they form a 1,2,… run."""
    runs: list[list[re.Match[str]]] = []
    current: list[re.Match[str]] = []
    expected = 1
    for match in _INLINE_NUMBER_RE.finditer(line):
        number = int(match.group(1))
        if number == expected:
            current.append(match)
            expected += 1
        elif number == 1:  # a new list starts ("...: 1. a 2. b")
            runs.append(current)
            current = [match]
            expected = 2
    runs.append(current)
    keep = [m for run in runs if len(run) >= 2 for m in run]
    if not keep:
        return line
    pieces: list[str] = []
    cursor = 0
    for match in keep:
        pieces.append(line[cursor : match.start()].rstrip())
        cursor = match.start()
    pieces.append(line[cursor:].strip())
    return "\n".join(p for p in pieces if p)


def _chunk_long_paragraph(paragraph: str) -> str:
    """Break one very long single-line paragraph at sentence ends, ~3 sentences each."""
    if len(paragraph) < _LONG_PARAGRAPH_CHARS:
        return paragraph
    sentences = _SENTENCE_END_RE.split(paragraph)
    if len(sentences) < 4:
        return paragraph
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if current and len(current) + len(sentence) > _CHUNK_CHARS:
            chunks.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        chunks.append(current)
    return "\n\n".join(chunks)


def _is_structural(line: str) -> bool:
    return bool(_LIST_RE.match(line) or _HEADING_RE.match(line))


def tidy_reply(text: str) -> str:
    """Repair a model's wall of text so :func:`render_markdown` can structure it.

    * inline numbered runs (``1. a 2. b 3. c``) go one per line;
    * inline ``###`` headings, ``•`` bullets and ``: - item`` bullets start a line;
    * a very long single-line paragraph is split at sentence ends.

    Fenced code blocks are left exactly as written. Only whitespace changes —
    never a word.
    """
    if not text:
        return text
    text = text.replace("\r\n", "\n")
    segments: list[tuple[bool, str]] = []  # (is_code, text)
    cursor = 0
    for match in _FENCE_RE.finditer(text):
        segments.append((False, text[cursor : match.start()]))
        segments.append((True, match.group(0)))
        cursor = match.end()
    segments.append((False, text[cursor:]))

    out: list[str] = []
    for is_code, segment in segments:
        if is_code:
            out.append(segment)
            continue
        lines: list[str] = []
        for line in segment.split("\n"):
            if line.strip() and not _is_structural(line) and "|" not in line:
                line = _INLINE_HEADING_RE.sub(r"\n\n\1 ", line)
                line = _LABEL_AFTER_SENTENCE_RE.sub("\n\n", line)
                line = _INLINE_BULLET_RE.sub("\n- ", line)
                line = _AFTER_COLON_DASH_RE.sub("\n- ", line)
                parts = [_split_inline_numbers(p) for p in line.split("\n")]
                parts = "\n".join(parts).split("\n")
                line = "\n".join(p if _is_structural(p) else _chunk_long_paragraph(p) for p in parts)
            lines.append(line)
        out.append("\n".join(lines))
    return re.sub(r"\n{3,}", "\n\n", "".join(out)).strip()
