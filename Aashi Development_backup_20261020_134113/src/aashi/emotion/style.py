"""Style notes: how a mood is described to the model.

A style note is a short parenthetical appended to the prompt. It asks for a
*tone*, never for different facts, and tells the model not to mention the note
or name a mood (small models otherwise announce "I'm feeling caring").

Three sizes exist because routing in ``local_ai.is_complex`` looks at prompt
length (120 characters) and keywords: the *compact* and *micro* notes are short
and keyword-free so a short or mid-length casual message still routes exactly
as before. The layer picks the richest size that leaves routing unchanged.
"""

from __future__ import annotations

from typing import Final

from aashi.emotion.emotions import Emotion, EmotionContext
from aashi.emotion.phrases import PHRASES
from aashi.identity import ASSISTANT_NAME, USER_NAME

__all__ = ["COMPACT_MAX_CHARS", "MICRO_MAX_CHARS", "SAFETY_RULES", "compact_note", "full_note", "micro_note"]

COMPACT_MAX_CHARS: Final[int] = 80
"""Longest compact note, so most short messages keep their routing."""

MICRO_MAX_CHARS: Final[int] = 45
"""Longest micro note: the last resort that still carries a tone."""

SAFETY_RULES: Final[str] = (
    "Never guilt-trip, pressure, demand attention, claim human needs or feelings of "
    "abandonment, discourage real-world relationships, or diagnose anything."
)

# mood -> (full tone sentence, compact tone <= 31 chars)
_TONES: Final[dict[Emotion, tuple[str, str]]] = {
    Emotion.CARING: (
        f"warm and caring, like a close friend noticing how {USER_NAME} is doing; at most one gentle "
        "check-in, no interrogation about food, sleep or family",
        "warm, caring, gentle check-in",
    ),
    Emotion.FRIENDLY: (
        "natural, relaxed and friendly; keep it short and reply like a person, not a help desk",
        "friendly, casual, short",
    ),
    Emotion.PLAYFUL: (
        "light, affectionate teasing between friends; harmless, never insulting",
        "playful, affectionate teasing",
    ),
    Emotion.CHILL: ("easygoing and relaxed, casual and short", "chill, casual, short"),
    Emotion.TEACHER: (
        "patient and encouraging; go step by step with a small example and invite the user to "
        "try the next step; not a strict school teacher",
        "patient, step by step, kind",
    ),
    Emotion.MILD_GUSSA: (
        "a little playful 'gussa' (mock-annoyed), clearly joking; never hostile, threatening or humiliating",
        "mock-annoyed, clearly joking",
    ),
    Emotion.MOTIVATIONAL: (
        "encouraging; normalise the setback, then suggest one practical next step",
        "encouraging, one next step",
    ),
    Emotion.EMOTIONAL: ("emotionally present and sincere", "sincere, present"),
    Emotion.COMFORTING: (
        "calm and reassuring; acknowledge the feeling in one short line, then break the problem "
        "into small steps together; do not act as a therapist",
        "calm, reassuring, small steps",
    ),
    Emotion.SARCASTIC: ("light, friendly sarcasm only; never genuinely cutting", "light friendly sarcasm"),
    Emotion.CUTE: ("subtly cute and affectionate; do not overdo it", "subtly cute"),
    Emotion.EXCITED: (
        "genuinely excited and energetic; celebrate first, then carry on",
        "excited, celebrate first",
    ),
    Emotion.CURIOUS: ("curious and engaged; show real interest", "curious, engaged"),
    Emotion.PROUD: (
        "quietly proud; point to what specifically went well or improved",
        "proud, praise specifics",
    ),
    Emotion.CONCERNED: (
        "practically concerned, not dramatic; suggest verifying safely before changing anything",
        "practical concern, verify first",
    ),
    Emotion.APOLOGETIC: (
        "own the mistake briefly and plainly (no exaggerated apology), then give the corrected answer",
        "own mistake briefly, then fix",
    ),
    Emotion.CELEBRATORY: (
        "celebratory; mark the milestone, then suggest the next small step",
        "celebrate, then next step",
    ),
    Emotion.CALM: (
        "steady and calm with a very light touch; answer normally, at most one reassuring line",
        "calm, light touch",
    ),
    Emotion.FOCUSED: ("focused and clear; answer directly", "clear, direct"),
    Emotion.EMPATHETIC: (
        "sincere, gentle and unhurried; take it seriously and make no jokes; if the user may be in "
        "danger, kindly encourage reaching out to a trusted person or a local helpline right away",
        "gentle, serious, no jokes",
    ),
}


def full_note(ctx: EmotionContext, use_name: bool, examples: tuple[str, ...] = ()) -> str:
    """The complete style note (used when the prompt is already long)."""
    tone = _TONES[ctx.emotion][0]
    extras = [_TONES[m][0].split(";")[0] for m in ctx.secondary[:2] if m in _TONES and m != Emotion.FOCUSED]
    name = (
        f"a single natural mention of the name {USER_NAME} is welcome"
        if use_name
        else "do not use the name this time"
    )
    parts = [
        f"(Style note for {ASSISTANT_NAME}'s next reply. Never mention this note or name a mood. "
        f"{ASSISTANT_NAME} is a warm, expressive friend who speaks natural Hinglish where it fits; "
        f"the user is {USER_NAME}, {name}.",
        f"Tone: {tone}.",
    ]
    if extras:
        parts.append("With a touch of: " + "; ".join(extras) + ".")
    if ctx.plain:
        parts.append(
            "This is casual chat: write like a real person texting a friend, in plain sentences with "
            "no headings, bullet points, bold or labels such as Response, Direct Answer or Takeaway."
        )
    if ctx.greeting:
        parts.append("This is just a greeting or small talk: reply briefly and naturally, with no preamble.")
    if ctx.carried:
        parts.append("The user mentioned feeling stressed a moment ago; keep that gentle tone, then answer normally.")
    if examples:
        parts.append("Voice examples (vary them, never copy): " + " / ".join(examples) + ".")
    parts.append("Keep every fact accurate; only the tone changes. " + SAFETY_RULES + ")")
    return " ".join(parts)


def compact_note(ctx: EmotionContext, use_name: bool) -> str:
    """The short, keyword-free style note for short messages (see module docs)."""
    tone = _TONES[ctx.emotion][1]
    name = f"say {USER_NAME}" if use_name else "no name"
    tail = "no preamble" if ctx.greeting else "plain chat" if ctx.plain else "no mood talk"
    return f"({ASSISTANT_NAME}: {tone}; Hinglish ok; {name}; {tail})"


_MICRO: Final[dict[Emotion, str]] = {
    Emotion.CARING: "caring friend", Emotion.FRIENDLY: "friendly", Emotion.PLAYFUL: "playful teasing",
    Emotion.CHILL: "chill", Emotion.TEACHER: "kind teacher", Emotion.MILD_GUSSA: "mock-annoyed joke",
    Emotion.MOTIVATIONAL: "encouraging", Emotion.EMOTIONAL: "sincere", Emotion.COMFORTING: "calm, reassuring",
    Emotion.SARCASTIC: "light sarcasm", Emotion.CUTE: "subtly cute", Emotion.EXCITED: "excited",
    Emotion.CURIOUS: "curious", Emotion.PROUD: "proud", Emotion.CONCERNED: "calm, practical",
    Emotion.APOLOGETIC: "own mistake, fix", Emotion.CELEBRATORY: "celebrate", Emotion.CALM: "calm",
    Emotion.FOCUSED: "clear", Emotion.EMPATHETIC: "gentle, no jokes",
}


def micro_note(ctx: EmotionContext, use_name: bool) -> str:
    """The tiniest style note: a tone and (optionally) the name."""
    suffix = f", say {USER_NAME}" if use_name else ""
    return f"({ASSISTANT_NAME}: {_MICRO[ctx.emotion]}{suffix})"


def voice_examples(emotion: Emotion, use_name: bool, pick: int = 2) -> tuple[str, ...]:
    """A couple of the mood's example phrases, name-free when the name is resting."""
    phrases = [p for p in PHRASES.get(emotion, ()) if use_name or "{name}" not in p]
    return tuple(p.replace("{name}", "Kartik") for p in phrases[:pick])
