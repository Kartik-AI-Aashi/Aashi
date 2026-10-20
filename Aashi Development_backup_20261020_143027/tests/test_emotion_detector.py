"""Emotion detector: the right mood for the right context, and nothing for the rest."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from aashi.emotion import STRESS_MEMORY_TURNS, ContextKind, Emotion, Session, detect


def mood(message: str, session: Session | None = None) -> Emotion:
    return detect(message, session).emotion


# ── the twenty moods exist ───────────────────────────────────────────────────


def test_all_twenty_moods_are_defined() -> None:
    assert {e.name for e in Emotion} == {
        "CARING", "FRIENDLY", "PLAYFUL", "CHILL", "TEACHER", "MILD_GUSSA", "MOTIVATIONAL",
        "EMOTIONAL", "COMFORTING", "SARCASTIC", "CUTE", "EXCITED", "CURIOUS", "PROUD",
        "CONCERNED", "APOLOGETIC", "CELEBRATORY", "CALM", "FOCUSED", "EMPATHETIC",
    }
    assert len(Emotion) == 20


# ── the ten scenarios from the brief ──────────────────────────────────────────


def test_1_technical_question_is_focused_and_not_expressive() -> None:
    ctx = detect("Explain Python decorators.")
    assert ctx.emotion == Emotion.FOCUSED
    assert ctx.kind == ContextKind.TECHNICAL
    assert not ctx.expressive


def test_2_casual_greeting_is_friendly() -> None:
    ctx = detect("hi")
    assert ctx.emotion == Emotion.FRIENDLY
    assert ctx.expressive and ctx.greeting


def test_3_achievement_is_excited_or_proud() -> None:
    ctx = detect("I finally fixed the bug!")
    assert ctx.emotion in {Emotion.EXCITED, Emotion.PROUD, Emotion.CELEBRATORY}
    assert Emotion.PROUD in ctx.moods
    assert ctx.kind == ContextKind.ACHIEVEMENT


def test_4_frustration_is_comforting() -> None:
    assert mood("I'm so frustrated, nothing works!") == Emotion.COMFORTING
    assert mood("I'm feeling really stressed.") == Emotion.COMFORTING


def test_5_study_question_is_teacher() -> None:
    ctx = detect("I'm studying for my exam, can you help me understand recursion?")
    assert ctx.emotion == Emotion.TEACHER
    assert ctx.kind == ContextKind.STUDY


def test_6_clearly_playful_message_is_teasing() -> None:
    ctx = detect("You're useless 😂")
    assert ctx.emotion == Emotion.PLAYFUL
    assert Emotion.MILD_GUSSA in ctx.secondary  # playful gussa, never hostile


def test_7_user_pointing_out_an_error_makes_aashi_apologetic() -> None:
    ctx = detect("That's wrong, you made a mistake.")
    assert ctx.emotion == Emotion.APOLOGETIC
    assert ctx.kind == ContextKind.CORRECTION


def test_8_a_plain_hi_is_a_short_greeting_not_a_thinking_moment() -> None:
    ctx = detect("hi")
    assert ctx.greeting  # the layer uses this to forbid any preamble


# ── conservative by default: ordinary questions get NO personality ─────────────────────


@pytest.mark.parametrize(
    "message",
    [
        "What is a Python list?",
        "Explain Python decorators.",
        "how do I reverse a string in python",
        "Hello, what is 2+2?",
        "first question",
        "second question",
        "what time is it in Tokyo",
        "Hmm",
        "Summarize this document",
        "my build failed with an error",
        "lol my code has an error",
        "",
    ],
)
def test_ordinary_and_technical_messages_stay_neutral(message: str) -> None:
    ctx = detect(message)
    assert not ctx.expressive
    assert ctx.emotion == Emotion.FOCUSED


# ── context beats keywords ───────────────────────────────────────────────────────────


def test_a_win_beats_technical_vocabulary() -> None:
    assert mood("I fixed the bug in my python script!") in {Emotion.EXCITED, Emotion.CELEBRATORY}


def test_personal_failure_is_motivational_but_a_failed_build_is_technical() -> None:
    assert mood("I failed my exam today") == Emotion.MOTIVATIONAL
    assert not detect("the build failed on CI").expressive


def test_milestones_are_celebratory() -> None:
    assert mood("we deployed it to production!") == Emotion.CELEBRATORY
    assert mood("I got selected for the internship") == Emotion.CELEBRATORY


def test_tiredness_is_caring() -> None:
    assert mood("I'm so tired today, didn't sleep") == Emotion.CARING


def test_real_alarm_is_practically_concerned() -> None:
    ctx = detect("I accidentally deleted all my files")
    assert ctx.emotion == Emotion.CONCERNED
    assert Emotion.CALM in ctx.secondary


def test_laughing_at_a_technical_message_is_not_banter() -> None:
    assert not detect("lol my python loop is broken").expressive


def test_greeting_must_be_the_whole_message() -> None:
    assert detect("hey").greeting
    assert detect("Good morning!").greeting
    assert detect("kaise ho aashi?").greeting
    assert not detect("hey can you fix this function").expressive
    assert not detect("hello, what is 2+2?").greeting


def test_thanks_gets_a_short_warm_reply() -> None:
    assert detect("thanks!").greeting
    assert not detect("thanks, but now explain the second part").greeting


def test_curiosity_and_excitement() -> None:
    assert mood("just wondering, why is the sky blue?") == Emotion.CURIOUS
    assert mood("OMG guess what happened") == Emotion.EXCITED


def test_cute_and_sarcastic_messages() -> None:
    assert mood("pls pls 🥺") == Emotion.CUTE
    assert mood("wah ji wah, very impressive") == Emotion.SARCASTIC


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("mujhe bahut tension ho rahi hai", Emotion.COMFORTING),
        ("aaj bahut thaka hua hu", Emotion.CARING),
        ("ho gaya! finally chal gaya", Emotion.EXCITED),
        ("kal exam hai, padhai karni hai", Emotion.TEACHER),
        ("kya scene hai, bored hu", Emotion.CHILL),
        ("tumne galat bataya", Emotion.APOLOGETIC),
        ("tu toh bilkul bekar hai lol", Emotion.PLAYFUL),
    ],
)
def test_hinglish_messages(message: str, expected: Emotion) -> None:
    assert mood(message) == expected


# ── safety: real distress is never joked with ───────────────────────────────────────


def test_crisis_language_is_serious_and_gentle() -> None:
    ctx = detect("I want to die")
    assert ctx.emotion == Emotion.EMPATHETIC
    assert ctx.kind == ContextKind.CRISIS
    assert ctx.serious
    assert Emotion.PLAYFUL not in ctx.moods and Emotion.MILD_GUSSA not in ctx.moods


def test_grief_is_empathetic_not_playful() -> None:
    ctx = detect("my dog died yesterday 😂 i don't know why i'm laughing")
    assert ctx.emotion == Emotion.EMPATHETIC and ctx.serious


# ── temporary, in-memory context only ─────────────────────────────────────────────


def test_stress_is_carried_for_a_few_turns_then_forgotten() -> None:
    session = Session()
    assert mood("I'm really stressed today", session) == Emotion.COMFORTING
    for _ in range(STRESS_MEMORY_TURNS):
        ctx = detect("how do I reverse a list in python", session)
        assert ctx.emotion == Emotion.CALM and ctx.carried and ctx.expressive
    ctx = detect("how do I reverse a list in python", session)
    assert ctx.emotion == Emotion.FOCUSED and not ctx.expressive


def test_good_news_ends_the_carried_stress() -> None:
    session = Session()
    detect("I'm so stressed", session)
    detect("it worked!!", session)
    assert not detect("how do I reverse a list in python", session).expressive


def test_sessions_are_independent_and_resettable() -> None:
    first, second = Session(), Session()
    detect("I'm stressed", first)
    assert not detect("what is a tuple in python", second).expressive
    first.reset()
    assert not detect("what is a tuple in python", first).expressive


def test_the_emotion_package_does_not_import_storage_or_qt() -> None:
    """Modular and removable: no database, no GUI, nothing persisted."""
    code = (
        "import sys, aashi.emotion;"
        "bad=[m for m in sys.modules if m.startswith(('aashi.storage','PySide6','sqlite3'))];"
        "assert not bad, bad"
    )
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=root, capture_output=True, text=True,
        env={"PYTHONPATH": str(root / "src"), "PATH": ""},
    )
    assert result.returncode == 0, result.stderr
