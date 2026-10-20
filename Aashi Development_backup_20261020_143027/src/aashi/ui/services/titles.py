"""Automatic conversation titles.

When the first question of a chat is sent, the sidebar needs a short, readable
name for it — the way ChatGPT names a conversation after what was asked.

Two stages, both Qt-free:

1. :func:`heuristic_title` — instant and offline. Strips conversational filler
   ("can you", "please", "explain", …) and keeps the first few meaningful
   words, so the sidebar shows a sensible name the moment the user presses
   Enter.
2. :func:`fetch_ai_title` — asks the active AI backend for a 2–5 word title and
   cleans the reply with :func:`clean_title`. It runs on a worker thread; if it
   fails or returns something unusable, the heuristic title simply stays.
"""

from __future__ import annotations

import logging
import re
from typing import Final

from aashi.ui.services import local_ai

__all__ = [
    "AI_TITLES_ENABLED",
    "MAX_TITLE_CHARS",
    "TITLE_PROMPT",
    "clean_title",
    "fetch_ai_title",
    "heuristic_title",
]

_logger = logging.getLogger(__name__)

AI_TITLES_ENABLED: bool = True
"""Master switch for the AI-generated title stage (the heuristic always runs)."""

MAX_TITLE_CHARS: Final[int] = 40
"""Longest title stored; longer text is cut at a word boundary."""

_MAX_WORDS: Final[int] = 6

TITLE_PROMPT: Final[str] = (
    "Write a very short title (2 to 5 words) that names the topic of the "
    "following chat message. Reply with ONLY the title: no quotes, no "
    "punctuation at the end, no markdown, no explanation.\n\n"
    "Message: {message}"
)

# Leading conversational filler removed before the title is cut. Longest
# phrases first so "can you please" wins over "can you".
_FILLER_PREFIXES: Final[tuple[str, ...]] = (
    "can you please", "could you please", "would you please", "will you please",
    "can you", "could you", "would you", "will you", "can i", "could i",
    "please", "pls", "hey aashi", "hi aashi", "hello aashi", "hey", "hi",
    "hello", "i want you to", "i want to know", "i need you to", "i need to",
    "i would like to know", "i would like you to", "i'd like to know",
    "tell me about", "tell me", "give me", "show me", "help me with",
    "help me", "i want to", "i wanna", "i have a question about",
    "i have a question", "what is the", "what are the", "what is", "what are",
    "what's", "whats", "how do i", "how do you", "how to", "how can i",
    "how does", "how do", "why is", "why does", "why do", "who is", "who was",
    "explain to me", "explain", "describe", "define",
)
_FILLER_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^(?:(?:" + "|".join(re.escape(p) for p in _FILLER_PREFIXES) + r")\b[\s,:-]*)+",
    re.IGNORECASE,
)
_SMALL_WORDS: Final[frozenset[str]] = frozenset(
    {"a", "an", "the", "of", "in", "on", "to", "for", "and", "or", "vs", "with", "at", "by"}
)
_ATTACHMENT_LINE: Final[re.Pattern[str]] = re.compile(r"\n[🖼📎].*$", re.DOTALL)


def _cut(words: list[str]) -> str:
    """Join ``words`` and cut at :data:`MAX_TITLE_CHARS` on a word boundary."""
    title = " ".join(words)
    if len(title) <= MAX_TITLE_CHARS:
        return title
    title = title[: MAX_TITLE_CHARS + 1].rsplit(" ", 1)[0]
    return title.rstrip(" ,;:-")


def _title_case(word: str, first: bool) -> str:
    if word.isupper() and len(word) > 1:  # acronyms: API, SQL, PDF
        return word
    if any(c.isupper() for c in word[1:]):  # camelCase / names: iPhone, PySide6
        return word
    if not first and word.lower() in _SMALL_WORDS:
        return word.lower()
    return word[:1].upper() + word[1:]


def heuristic_title(text: str, fallback: str = "New chat") -> str:
    """Derive a short title from the user's first message, offline.

    Args:
        text: The question as typed (an attachment label line is ignored).
        fallback: Returned when nothing meaningful is left.

    Returns:
        A title of at most :data:`MAX_TITLE_CHARS` characters.
    """
    text = _ATTACHMENT_LINE.sub("", text or "").strip()
    # Only the first sentence/line names the topic.
    text = re.split(r"[\n\r]|(?<=[.!?])\s", text, maxsplit=1)[0]
    stripped = _FILLER_PATTERN.sub("", text).strip()
    candidate = stripped or text
    # A title reads better without a leading article: "Binary Tree", not "A Binary Tree".
    candidate = re.sub(r"^(?:a|an|the)\s+(?=\S+\s*\S)", "", candidate, flags=re.IGNORECASE)
    candidate = re.sub(r"[`*_#>\"]+", "", candidate)
    candidate = re.sub(r"[?!.,;:]+$", "", candidate).strip()
    words = [w for w in candidate.split() if w]
    if not words:
        return fallback
    words = words[:_MAX_WORDS]
    # Never end on a dangling article/preposition ("Plan a 5 Day Trip to").
    while len(words) > 1 and words[-1].lower() in _SMALL_WORDS:
        words.pop()
    titled = [_title_case(w, i == 0) for i, w in enumerate(words)]
    return _cut(titled) or fallback


def clean_title(raw: str) -> str | None:
    """Sanitise a model's title reply; return ``None`` if it is unusable."""
    if not raw:
        return None
    line = next((ln.strip() for ln in raw.strip().splitlines() if ln.strip()), "")
    line = re.sub(r"^(?:title|name|topic)\s*[:\-]\s*", "", line, flags=re.IGNORECASE)
    line = re.sub(r"[`*_#>\"“”‘’]+", "", line).strip()
    line = re.sub(r"[.!?:;,\s-]+$", "", line)
    words = line.split()
    if not 1 <= len(words) <= 8:
        return None
    if len(line) > MAX_TITLE_CHARS:
        line = _cut(words)
    lowered = line.lower()
    if lowered in {"something went wrong", "my name is aashi"} or lowered.startswith("i'm sorry"):
        return None
    return line or None


def fetch_ai_title(question: str) -> str | None:
    """Ask the AI backend for a title for ``question`` (blocking).

    Returns ``None`` on any failure so the caller keeps the heuristic title.
    """
    if not AI_TITLES_ENABLED:
        return None
    try:
        reply = local_ai.fetch_response_hybrid(TITLE_PROMPT.format(message=question[:500]))
    except Exception as exc:  # network down, no key, local model absent …
        _logger.info("AI title unavailable (%s); keeping heuristic title.", exc)
        return None
    return clean_title(reply)
