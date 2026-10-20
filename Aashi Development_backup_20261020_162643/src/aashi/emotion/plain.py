"""Plain-conversation clean-up: make a casual reply read like a person texting.

Small and mid-size models often wrap even gossip in headings, bullet points and
labels such as "Response", "Direct Answer" or "Takeaway". In casual chat that
looks robotic, so for conversational contexts only (``EmotionContext.plain``)
this module strips that scaffolding and keeps the sentences.

It only removes *markup and labels*; no sentence is rewritten or dropped.
Replies that contain code blocks or tables are returned untouched, and
explanations / technical answers never reach this function.
"""

from __future__ import annotations

import re
from typing import Final

__all__ = ["plainify"]

_EMOJI: Final = "[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F\u200d]"
_LABELS: Final = r"(?:quick answer|direct answer|response|answer|takeaway|summary|tl;?dr|bottom line)"

# A line that is only a label (optionally a heading, bold, with a trailing emoji): "## Response ✨"
_LABEL_LINE: Final = re.compile(
    rf"^[ \t]*(?:#{{1,6}}[ \t]*)?[*_]*{_LABELS}[*_]*[ \t]*[:\-–—]?[*_]*[ \t]*(?:{_EMOJI}[ \t]*)*$",
    re.IGNORECASE | re.MULTILINE,
)
# A label that prefixes a sentence: "• **Direct Answer:** Main tumhare saath..." -> "Main tumhare saath..."
_LABEL_PREFIX: Final = re.compile(
    rf"^([ \t]*)(?:[-*+•][ \t]+)?[*_]*{_LABELS}[*_]*[ \t]*:[*_]*[ \t]*", re.IGNORECASE | re.MULTILINE
)
_HEADING: Final = re.compile(r"^[ \t]*#{1,6}[ \t]+", re.MULTILINE)
_BULLET: Final = re.compile(r"^[ \t]*(?:[-*+•]|\d{1,3}[.)])[ \t]+", re.MULTILINE)
_BOLD: Final = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1")
_ITALIC: Final = re.compile(r"(?<![\w*])\*(?=[^\s*])([^*\n]+?)(?<=[^\s*])\*(?![\w*])")
_TABLE_ROW: Final = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$", re.MULTILINE)


def plainify(text: str) -> str:
    """Strip headings, bullets, bold and "Response/Takeaway" labels from ``text``.

    Args:
        text: A reply to a casual message.

    Returns:
        The same sentences as plain conversational text. Returns ``text``
        unchanged if it holds a code block or a table, or if stripping would
        leave nothing.
    """
    if not text or "```" in text or _TABLE_ROW.search(text):
        return text
    out = _LABEL_LINE.sub("", text)
    out = _LABEL_PREFIX.sub(r"\1", out)
    out = _HEADING.sub("", out)
    out = _BULLET.sub("", out)
    out = _BOLD.sub(r"\2", out)
    out = _ITALIC.sub(r"\1", out)
    out = "\n".join(line.rstrip() for line in out.split("\n"))
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return out or text
