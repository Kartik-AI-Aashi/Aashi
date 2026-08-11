"""Lightweight markdown → HTML converter for QLabel RichText rendering.

The chat bubble's :class:`QLabel` uses ``Qt.TextFormat.RichText``, which
treats its content as HTML.  In HTML, runs of whitespace collapse and leading
spaces disappear — destroying the alignment of text diagrams that the model
produces inside fenced code blocks.

This module converts *only* fenced code blocks (```` ``` ````) to ``<pre>``
HTML, where the browser preserves every space and line break.  All other text
is HTML-escaped but otherwise left untouched so the existing
``_format_assistant_reply`` paragraph logic and the ``QLabel`` ``\\n`` →
``<br>`` conversion continue to work exactly as before.

The module is Qt-free and testable in pure Python.
"""

from __future__ import annotations

import html as _html
import re
from typing import Final

__all__ = ["render_markdown"]

_FENCE_RE: Final[re.Pattern[str]] = re.compile(
    r"```(\w*)\n(.*?)```",
    re.DOTALL,
)
"""Matches fenced code blocks: `` ```lang\\n...\\n``` ``.

Group 1 is the optional language tag (e.g. ``text``, ``python``).
Group 2 is the code content between the opening and closing fences.
"""


def render_markdown(text: str) -> str:
    """Convert *text* to HTML suitable for :class:`QLabel` RichText rendering.

    Fenced code blocks become ``<pre>`` elements whose content is
    HTML-escaped, preserving every space and line break — critical for
    flowcharts, ASCII diagrams and code listings.

    Text outside code blocks is HTML-escaped (``<``, ``>``, ``&``) so no
    user-visible content can inject raw HTML.  Line breaks (``\\n``) are
    left as-is; ``QLabel`` in RichText mode already converts them to
    ``<br>`` tags internally.

    Args:
        text: Raw assistant reply (may contain fenced code blocks).

    Returns:
        An HTML string ready for ``QLabel.setText()``.
    """
    parts = _FENCE_RE.split(text)
    result: list[str] = []

    for i, part in enumerate(parts):
        remainder = i % 3
        if remainder == 0:
            # Plain text — escape HTML entities but keep newlines.
            result.append(_html.escape(part))
        elif remainder == 1:
            # Language tag (e.g. "text", "python") — discarded.
            pass
        else:
            # Code content — strip one trailing newline, then wrap in <pre>.
            code = part.rstrip("\n")
            result.append(f"<pre>{_html.escape(code)}</pre>")

    return "".join(result)
