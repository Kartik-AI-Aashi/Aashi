"""The emotion layer: prompt preparation, routing safety, reply cleaning."""

from __future__ import annotations

import random
import re
from pathlib import Path

import pytest

from aashi.emotion import layer as layer_module
from aashi.emotion import phrases, style
from aashi.emotion.emotions import ContextKind, Emotion, EmotionContext
from aashi.emotion.layer import USER_NAME, EmotionLayer
from aashi.ui.services import local_ai
from aashi.ui.services.local_ai import is_complex

EXPRESSIVE = [
    ("hi", "greeting"),
    ("I'm feeling really stressed.", "comforting"),
    ("I finally fixed the bug!", "excited"),
    ("You're useless 😂", "playful"),
    ("I'm studying for my exam, help me with recursion", "teacher"),
    ("that's wrong, you made a mistake", "apologetic"),
    ("I failed my exam today", "motivational"),
    ("I'm so tired today", "caring"),
    ("thanks!", "thanks"),
    ("kaise ho aashi", "smalltalk"),
]
TECHNICAL = [
    "Explain Python decorators.",
    "What is a Python list?",
    "how do I reverse a string in python",
    "Hello, what is 2+2?",
    "my build failed with an error",
    "first question",
]


def fresh(seed: int = 0) -> EmotionLayer:
    return EmotionLayer(rng=random.Random(seed))


def ctx(emotion: Emotion, **kw) -> EmotionContext:
    return EmotionContext(emotion, ContextKind.OTHER, expressive=True, **kw)


# ── technical / neutral prompts are untouched, byte for byte ──────────────────────────


@pytest.mark.parametrize("message", TECHNICAL)
def test_technical_and_neutral_prompts_pass_through_byte_for_byte(message: str) -> None:
    prompt = f"User: {message}"
    prepared = fresh().prepare(prompt, message)
    assert prepared.prompt == prompt
    assert not prepared.note_applied
    assert not prepared.context.expressive


def test_transcript_with_history_is_untouched_for_technical_questions() -> None:
    prompt = "User: hi\n\nAssistant: Heyy!\n\nUser: Explain Python decorators."
    assert fresh().prepare(prompt, "Explain Python decorators.").prompt == prompt


# ── routing is never changed ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(("message", "_label"), EXPRESSIVE)
@pytest.mark.parametrize("history_chars", [0, 20, 40, 60, 80, 100, 130, 300])
def test_routing_decision_is_identical_with_and_without_the_note(
    message: str, _label: str, history_chars: int
) -> None:
    """The headline guarantee: ``is_complex`` gives the same answer for the prompt
    the model receives as for the prompt the existing pipeline would have sent."""
    history = ("x" * history_chars + "\n\n") if history_chars else ""
    prompt = f"{history}User: {message}"
    prepared = fresh().prepare(prompt, message)
    assert is_complex(prepared.prompt) == is_complex(prompt)


def test_routing_is_unchanged_for_every_mood_and_length() -> None:
    for emotion in Emotion:
        for length in range(0, 200, 7):
            prompt = "a" * length
            layer = fresh()
            layer._session.stressed_turns_left = 0
            context = ctx(emotion)
            layer.analyse = lambda _m, c=context: c  # type: ignore[method-assign]
            prepared = layer.prepare(prompt, "x")
            assert is_complex(prepared.prompt) == is_complex(prompt), (emotion, length)


def test_richest_note_that_keeps_routing_is_chosen() -> None:
    sizes = {}
    for label, prefix in (("complex", "explain " + "x" * 5), ("short", ""), ("mid", "y" * 40), ("long", "z" * 100)):
        message = "I'm stressed" if label != "complex" else "I'm stressed, explain this"
        prompt = f"{prefix}\n\nUser: {message}" if prefix else f"User: {message}"
        prepared = fresh().prepare(prompt, message)
        sizes[label] = (len(prepared.prompt) - len(prompt), prepared.note_applied)
    assert sizes["complex"][0] > sizes["short"][0]  # already complex → full note
    assert sizes["short"][0] > sizes["mid"][0] > 0  # shrinks to keep routing
    assert sizes["long"] == (0, False)  # nothing fits → prompt unchanged, no note


# ── the notes themselves ────────────────────────────────────────────────────────────


def test_compact_and_micro_notes_are_short_and_keyword_free_for_every_mood() -> None:
    for emotion in Emotion:
        for use_name in (True, False):
            for greeting in (True, False):
                context = ctx(emotion, greeting=greeting)
                compact = style.compact_note(context, use_name)
                micro = style.micro_note(context, use_name)
                assert len(compact) <= style.COMPACT_MAX_CHARS, compact
                assert len(micro) <= style.MICRO_MAX_CHARS, micro
                for note in (compact, micro):
                    assert not any(k in note.lower() for k in local_ai._COMPLEX_KEYWORDS), note
                    assert "ansh" not in note.lower()


def test_every_mood_has_a_tone_a_micro_tone_and_phrases() -> None:
    for emotion in Emotion:
        assert style._TONES[emotion][0] and style._TONES[emotion][1]
        assert style._MICRO[emotion]
        assert phrases.PHRASES[emotion]


def test_full_note_forbids_manipulation_and_naming_moods() -> None:
    note = style.full_note(ctx(Emotion.COMFORTING), use_name=True)
    lowered = note.lower()
    assert "never mention this note or name a mood" in lowered
    for rule in ("guilt-trip", "pressure", "abandonment", "diagnose"):
        assert rule in lowered
    assert "only the tone changes" in lowered
    assert "Kartik" in note


def test_full_note_for_a_greeting_forbids_a_preamble() -> None:
    assert "no preamble" in style.full_note(ctx(Emotion.FRIENDLY, greeting=True), True)
    assert "no preamble" in style.compact_note(ctx(Emotion.FRIENDLY, greeting=True), True)


def test_serious_moments_get_no_jokes() -> None:
    assert "no jokes" in style.full_note(ctx(Emotion.EMPATHETIC, serious=True), True).lower()


# ── the user's name is natural, not repetitive ──────────────────────────────────────────


def test_name_is_offered_then_rests_for_a_few_replies() -> None:
    layer = fresh()
    first = layer.prepare("User: hi", "hi")
    assert first.use_name and "say Kartik" in first.prompt
    layer.finish("Heyy Kartik! How's your day going?", first)
    for _ in range(3):  # the name rests for three replies...
        again = layer.prepare("User: hi", "hi")
        assert not again.use_name and "no name" in again.prompt
        layer.finish("Heyy! Kya haal?", again)
    assert layer.prepare("User: hi", "hi").use_name  # ...then may be used again


def test_reset_makes_the_name_available_again_and_clears_mood() -> None:
    layer = fresh()
    layer.finish("Hi Kartik!", layer.prepare("User: hi", "hi"))
    layer.analyse("I'm stressed")
    layer.reset()
    assert layer.prepare("User: hi", "hi").use_name
    assert not layer.analyse("what is a tuple in python").expressive


# ── finish(): cleaning without changing facts ────────────────────────────────────────


def test_the_wrong_name_is_always_corrected() -> None:
    layer = fresh()
    assert layer.finish("Hello Ansh, nice to see you!") == "Hello Kartik, nice to see you!"
    assert layer.finish("ANSH and ansh") == "Kartik and Kartik"
    assert layer.finish("Anshul is a different name") == "Anshul is a different name"


def test_the_name_inside_code_is_left_alone() -> None:
    reply = "Use this:\n```python\nansh = 1\nprint(ansh)\n```\nOkay Ansh?"
    out = fresh().finish(reply)
    assert "ansh = 1" in out and "print(ansh)" in out
    assert out.endswith("Okay Kartik?")


def test_an_echoed_style_note_is_removed() -> None:
    reply = "(Aashi: friendly, casual, short; Hinglish ok; say Kartik; no preamble)\nHeyy Kartik!"
    assert fresh().finish(reply) == "Heyy Kartik!"
    leaked = "Heyy!\n(Style note for Aashi's next reply. Never mention this note.)"
    assert fresh().finish(leaked) == "Heyy!"


def test_mood_announcements_are_removed() -> None:
    assert fresh().finish("I'm feeling caring right now. Kaise ho?") == "Kaise ho?"
    assert fresh().finish("*I am feeling so playful today*\nHaha okay!") == "Haha okay!"
    assert fresh().finish("(Caring mode) Hey, relax.") == "Hey, relax."


def test_several_leaks_at_once_are_all_removed() -> None:
    layer = fresh()
    hi = layer.prepare("User: hi", "hi")
    raw = "Wait, let me think...\nI'm feeling caring right now. Heyy Ansh! (Aashi: friendly)"
    assert layer.finish(raw, hi) == "Heyy Kartik!"


def test_an_inline_style_note_is_removed_wherever_it_appears() -> None:
    assert fresh().finish("Sure thing (Aashi: calm, reassuring; Hinglish ok) here you go.") == "Sure thing here you go."
    full = "Here is the answer. (Style note for Aashi's next reply. Never mention this note.)"
    assert fresh().finish(full) == "Here is the answer."


@pytest.mark.parametrize(
    "reply",
    (
        "Assistant: My name is Aashi.",
        "Assistant:\nMy name is Aashi.",
        "System:\nAssistant:\nMy name is Aashi.",
    ),
)
def test_transport_role_markers_are_removed_but_reply_content_survives(reply: str) -> None:
    assert fresh().finish(reply) == "My name is Aashi."


def test_ordinary_use_of_the_word_assistant_is_not_stripped() -> None:
    reply = "I am an assistant: I can help you plan the next step."
    assert fresh().finish(reply) == reply


def test_mood_words_in_a_normal_sentence_are_not_removed() -> None:
    sentence = "Sometimes I'm feeling caring toward my plants, honestly."
    assert fresh().finish(sentence) == sentence


def test_thinking_preamble_is_removed_only_for_a_plain_greeting() -> None:
    layer = fresh()
    hi = layer.prepare("User: hi", "hi")
    assert layer.finish("Wait, let me think... Heyy Kartik!", hi) == "Heyy Kartik!"
    tech = layer.prepare("User: what is a tuple in python", "what is a tuple in python")
    assert layer.finish("Hmm... a tuple is immutable.", tech) == "Hmm... a tuple is immutable."


def test_finish_never_returns_an_empty_reply() -> None:
    assert fresh().finish("(Aashi: friendly)") == "(Aashi: friendly)"


def test_finish_is_idempotent() -> None:
    layer = fresh()
    hi = layer.prepare("User: hi", "hi")
    once = layer.finish("Wait, let me think...\nHello Ansh!", hi)
    assert layer.finish(once, hi) == once


def test_a_technical_reply_is_not_touched_at_all() -> None:
    """Emotion must never alter a factual answer."""
    reply = (
        "A decorator wraps a function:\n\n```python\n@timer\ndef f(x):\n    return x * 2\n```\n\n"
        "1. It runs at definition time.\n2. `functools.wraps` keeps metadata.\n\nSee https://docs.python.org/3/ (v3.12)."
    )
    layer = fresh()
    prepared = layer.prepare("User: Explain Python decorators.", "Explain Python decorators.")
    assert layer.finish(reply, prepared) == reply


@pytest.mark.parametrize(("message", "_"), EXPRESSIVE)
def test_numbers_code_and_urls_survive_finish_for_every_context(message: str, _: str) -> None:
    reply = "The answer is 42 (π≈3.14159). Run `pip install x==1.2.3`, see https://example.com/a?b=1&c=2."
    layer = fresh()
    prepared = layer.prepare(f"User: {message}", message)
    out = layer.finish(reply, prepared)
    for fact in ("42", "3.14159", "`pip install x==1.2.3`", "https://example.com/a?b=1&c=2"):
        assert fact in out


# ── fallback opener: only when the note could not ride along ──────────────────────────


# A SIMPLE prompt (<= 120 chars, no routing keyword) that is too long for any note to
# fit without tipping it over the threshold: the layer must send no note at all.
LONG_STRESS = "I'm so stressed about everything going on with my exams and the assignments today, can't focus"


def _no_note_prepared(layer: EmotionLayer, message: str):
    prompt = f"User: {message}"
    assert not is_complex(prompt)
    prepared = layer.prepare(prompt, message)
    assert not prepared.note_applied  # nothing fit; routing was preserved
    assert prepared.prompt == prompt
    return prepared


def test_opener_is_added_when_no_note_could_be_sent() -> None:
    layer = fresh(3)
    prepared = _no_note_prepared(layer, LONG_STRESS)
    reply = "Let's slow down. Breathe first, then write a short list of what is left."
    out = layer.finish(reply, prepared)
    opener, _, rest = out.partition("\n\n")
    assert opener.replace("Kartik", "{name}") in phrases.OPENERS[Emotion.COMFORTING]
    assert rest == reply


def test_no_opener_when_the_note_was_applied() -> None:
    layer = fresh()
    prepared = layer.prepare("User: I'm stressed", "I'm stressed")
    assert prepared.note_applied
    assert layer.finish("Ek-ek karke dekhte hain.", prepared) == "Ek-ek karke dekhte hain."


def test_openers_vary_between_replies() -> None:
    layer = fresh(7)
    seen = set()
    for _ in range(6):
        prepared = _no_note_prepared(layer, LONG_STRESS)
        seen.add(layer.finish("ok", prepared).split("\n\n")[0])
    assert len(seen) >= 2


def test_the_same_opener_never_repeats_back_to_back() -> None:
    layer = fresh(1)
    last = None
    for _ in range(12):
        prepared = _no_note_prepared(layer, LONG_STRESS)
        opener = layer.finish("ok", prepared).split("\n\n")[0]
        assert opener != last
        last = opener


def test_no_opener_for_greetings_technical_or_carried_context() -> None:
    layer = fresh()
    greet = layer.prepare("User: hi", "hi")
    assert layer.finish("Hello!", greet) == "Hello!"
    for prepared in (
        layer.prepare("User: Explain Python decorators.", "Explain Python decorators."),
    ):
        assert layer.finish("Decorators wrap functions.", prepared) == "Decorators wrap functions."
    layer.analyse("I'm stressed")
    carried = layer.prepare("q" * 70 + "\n\nUser: how to reverse a list", "how to reverse a list")
    assert carried.context.carried and not carried.note_applied
    assert layer.finish("Use reversed().", carried) == "Use reversed()."


def test_the_name_in_an_opener_respects_the_resting_rule() -> None:
    layer = fresh(2)
    layer._turns_since_name = 0  # name used a moment ago → must rest
    for _ in range(10):
        prepared = _no_note_prepared(layer, LONG_STRESS)
        assert not prepared.use_name
        assert "Kartik" not in layer.finish("ok", prepared).split("\n\n")[0]
        layer._turns_since_name = 0


# ── the layer is a removable switch ──────────────────────────────────────────────────────


def test_disabled_layer_is_a_transparent_pass_through(monkeypatch) -> None:
    monkeypatch.setattr(layer_module, "EMOTION_LAYER_ENABLED", False)
    layer = fresh()
    assert layer.prepare("User: hi", "hi").prompt == "User: hi"
    assert not layer.prepare("User: I'm stressed", "I'm stressed").note_applied
    assert layer.finish("Hello Ansh (Aashi: x)") == "Hello Ansh (Aashi: x)"


# ── no manipulation, no hostility, no wrong name ─────────────────────────────────────


def _all_phrases() -> list[str]:
    banks = list(phrases.PHRASES.values()) + list(phrases.OPENERS.values())
    return [p for bank in banks for p in bank]


@pytest.mark.parametrize(
    "bad",
    ["i missed you", "miss talking", "don't leave", "dont leave", "leave me", "alone", "abandon",
     "only you", "need you", "stupid", "idiot", "shut up", "hate you", "worthless", "kill", "ansh"],
)
def test_phrase_banks_contain_nothing_manipulative_or_hostile(bad: str) -> None:
    assert not [p for p in _all_phrases() if bad in p.lower()]


def test_no_source_file_uses_the_wrong_name_except_the_filter() -> None:
    root = Path(layer_module.__file__).parent
    offenders = [
        f.name for f in root.glob("*.py")
        if f.name != "layer.py" and re.search(r"\bansh\b", f.read_text(encoding="utf-8"), re.IGNORECASE)
    ]
    assert offenders == []


def test_user_name_constant() -> None:
    assert USER_NAME == "Kartik"
