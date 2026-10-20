"""The emotion / personality layer: a small, independent, removable component.

::

    user message ─► existing Aashi pipeline (unchanged) ─► reply
         │                                                   │
         ▼                                                   ▼
    detect context ─► prepare(): optional style note     finish(): tidy leaks,
    (detector.py)     appended to the prompt             optional fallback opener

What it does
------------
* :meth:`EmotionLayer.prepare` decides the mood for the user's message and — only
  for expressive contexts (greetings, stress, wins, banter, study …) — appends a
  short style note to the prompt. **Technical and neutral messages are returned
  byte-for-byte unchanged**, so the existing behaviour is untouched.
* :meth:`EmotionLayer.finish` cleans the reply: for casual chat it strips headings,
  bullets, bold and "Response / Takeaway" labels so Aashi reads like a person texting
  (explanations and technical answers keep their structure); it keeps the user's name right,
  strips leaked meta text (an echoed style note, "I'm feeling caring right now",
  a "let me think…" preamble before a plain "hi") and — only when the style note
  could not be sent — adds one short, varied opener. It never alters facts.

Guarantees
----------
* **Routing is never changed.** ``local_ai.is_complex`` judges the whole prompt
  (length > 120 characters or keywords). A note is only added in a size that
  leaves that decision exactly as it would have been without it.
* **Presentation only.** Emotion colours wording; it never rewrites an answer.
* **No persistence.** The only memory is a few in-memory counters, cleared by
  :meth:`reset` when the chat changes. Nothing is stored in the database.
* **No manipulation.** Notes forbid guilt-tripping, pressure, clinginess and
  diagnoses; see :data:`aashi.emotion.style.SAFETY_RULES`.

Remove the layer by deleting the ``aashi.emotion`` package and the four hook
lines in the chat window, or set :data:`EMOTION_LAYER_ENABLED` to ``False``.
"""

from __future__ import annotations

import random
import re
from collections.abc import Callable
from dataclasses import dataclass

from aashi.emotion import phrases, style
from aashi.emotion.plain import plainify
from aashi.emotion.detector import Session, detect
from aashi.emotion.emotions import NEUTRAL, ContextKind, Emotion, EmotionContext

__all__ = ["ASSISTANT_NAME", "EMOTION_LAYER_ENABLED", "USER_NAME", "EmotionLayer", "Prepared"]

EMOTION_LAYER_ENABLED: bool = True
"""Master switch. ``False`` makes the layer a transparent pass-through."""

ASSISTANT_NAME = "Aashi"
USER_NAME = "Kartik"

_NAME_REST_TURNS = 3
"""Replies that must pass before the user's name is offered again."""

_SEPARATOR = "\n\n"
_FENCE = re.compile(r"(```.*?```)", re.DOTALL)
_WRONG_NAME = re.compile(r"\bAnsh\b", re.IGNORECASE)

_MOOD_WORDS = "|".join(
    sorted({e.value.replace("_", " ") for e in Emotion} | {"caring", "playful", "teasing", "excited"}, key=len, reverse=True)
)
_MOOD_ANNOUNCEMENT = re.compile(
    rf"^\s*[*_]*\s*(?:i['’]?m|i am)\s+feeling\s+(?:so\s+|very\s+|really\s+)?(?:{_MOOD_WORDS})"
    rf"(?:\s+right now|\s+today)?\s*[*_]*[.!…]*[ \t]*\n*",
    re.IGNORECASE,
)
_MODE_TAG = re.compile(rf"^\s*[(\[*]\s*(?:{_MOOD_WORDS})\s*(?:mode|tone|mood)?\s*[)\]*]\s*\n*", re.IGNORECASE)
_ECHOED_NOTE = re.compile(r"^[ \t]*[(\[]?[ \t]*(?:style note|aashi:)[^\n]*(?:\n|$)", re.IGNORECASE | re.MULTILINE)
_INLINE_COMPACT_NOTE = re.compile(r"[ \t]*\(aashi:[^()\n]*\)", re.IGNORECASE)
_INLINE_FULL_NOTE = re.compile(r"[ \t]*\(style note[^\n]*$", re.IGNORECASE | re.MULTILINE)
_THINKING_PREAMBLE = re.compile(
    r"^\s*(?:wait,?\s*)?(?:let me think|give me a second|okay,? let'?s see|hmm+)\s*[.…!]*\s*\n*", re.IGNORECASE
)


@dataclass(frozen=True)
class Prepared:
    """The outcome of :meth:`EmotionLayer.prepare` for one message.

    Attributes:
        prompt: The prompt to send. Identical to the input unless ``note_applied``.
        context: The detected emotion context.
        note_applied: Whether a style note was appended to the prompt.
        use_name: Whether this turn is allowed to use the user's name.
    """

    prompt: str
    context: EmotionContext
    note_applied: bool = False
    use_name: bool = False


def _default_is_complex(prompt: str) -> bool:
    """The real routing predicate; falls back to "never complex" if unavailable."""
    try:
        from aashi.ui.services.local_ai import is_complex
    except Exception:  # pragma: no cover - the layer must never break the app
        return False
    return is_complex(prompt)


class EmotionLayer:
    """Wraps the existing pipeline with a mood-aware presentation layer.

    Args:
        is_complex: The routing predicate used to keep routing unchanged.
            Defaults to ``local_ai.is_complex``.
        rng: Random source for picking phrases (inject a seeded one in tests).
    """

    def __init__(
        self,
        is_complex: Callable[[str], bool] | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self._is_complex = is_complex or _default_is_complex
        self._rng = rng or random.Random()
        self._session = Session()
        self._turns_since_name = _NAME_REST_TURNS  # the very first reply may use the name
        self._last_opener: str | None = None

    # -- state ----------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        """Whether the layer is active (module-level switch)."""
        return EMOTION_LAYER_ENABLED

    def reset(self) -> None:
        """Forget the temporary mood: call whenever the chat changes."""
        self._session.reset()
        self._turns_since_name = _NAME_REST_TURNS
        self._last_opener = None

    # -- before the model -----------------------------------------------------------

    def analyse(self, message: str) -> EmotionContext:
        """Detect the mood for ``message`` (updates the temporary session mood)."""
        if not self.enabled:
            return NEUTRAL
        return detect(message, self._session)

    def prepare(self, prompt: str, message: str) -> Prepared:
        """Decide the mood and, if it calls for one, append a style note.

        Args:
            prompt: The prompt the existing pipeline would send.
            message: The user's latest message (what the detector reads).

        Returns:
            A :class:`Prepared`. For technical / neutral messages, or when
            disabled, ``prompt`` is returned exactly as given.
        """
        context = self.analyse(message)
        if not (self.enabled and context.expressive):
            return Prepared(prompt, context)

        use_name = self._turns_since_name >= _NAME_REST_TURNS
        examples = style.voice_examples(context.emotion, use_name)
        notes = (
            style.full_note(context, use_name, examples),
            style.compact_note(context, use_name),
            style.micro_note(context, use_name),
        )
        was_complex = self._is_complex(prompt)
        for note in notes:
            candidate = prompt + _SEPARATOR + note
            # Never change where the prompt is routed.
            if was_complex or not self._is_complex(candidate):
                return Prepared(candidate, context, note_applied=True, use_name=use_name)
        return Prepared(prompt, context, note_applied=False, use_name=use_name)

    # -- after the model ----------------------------------------------------------------

    def finish(self, reply: str, prepared: Prepared | None = None) -> str:
        """Tidy ``reply`` for presentation. Never changes facts.

        Args:
            reply: The text the existing pipeline produced.
            prepared: The matching :meth:`prepare` result, if any.

        Returns:
            The reply with the user's name corrected and leaked meta text
            removed; plus one short opener when the style note could not be sent.
        """
        if not reply or not self.enabled:
            return reply
        context = prepared.context if prepared else NEUTRAL
        text = self._clean(reply, context)
        if prepared is not None and not prepared.note_applied:
            text = self._with_opener(text, prepared)
        self._turns_since_name = 0 if USER_NAME.lower() in text.lower() else self._turns_since_name + 1
        return text

    def _clean(self, reply: str, context: EmotionContext) -> str:
        parts = _FENCE.split(reply)
        for i in range(0, len(parts), 2):  # outside code fences only
            parts[i] = _WRONG_NAME.sub(USER_NAME, parts[i])
        text = "".join(parts)

        cleaned = _ECHOED_NOTE.sub("", text)
        cleaned = _INLINE_COMPACT_NOTE.sub("", cleaned)
        cleaned = _INLINE_FULL_NOTE.sub("", cleaned)
        # Leading meta text, outermost first: a "let me think" preamble, then a mood
        # announcement or tag that may have been sitting behind it.
        if context.greeting:
            cleaned = _THINKING_PREAMBLE.sub("", cleaned, count=1)
        cleaned = _MOOD_ANNOUNCEMENT.sub("", cleaned, count=1)
        cleaned = _MODE_TAG.sub("", cleaned, count=1)
        cleaned = cleaned.strip()
        if context.plain:
            # Casual chat reads like a person texting: no headings, bullets or labels.
            cleaned = plainify(cleaned)
        return cleaned or text  # never return an empty reply

    def _with_opener(self, text: str, prepared: Prepared) -> str:
        context = prepared.context
        if (
            context.emotion not in phrases.OPENER_EMOTIONS
            or context.greeting
            or context.carried
            or context.kind == ContextKind.TECHNICAL and context.emotion != Emotion.CONCERNED
        ):
            return text
        options = [
            o for o in phrases.OPENERS[context.emotion]
            if (prepared.use_name or "{name}" not in o) and o != self._last_opener
        ] or [o for o in phrases.OPENERS[context.emotion] if "{name}" not in o]
        if not options:
            return text
        opener = self._rng.choice(options)
        self._last_opener = opener
        return f"{opener.replace('{name}', USER_NAME)}\n\n{text}"
