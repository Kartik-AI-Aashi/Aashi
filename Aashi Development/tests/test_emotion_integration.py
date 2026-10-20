"""The emotion layer inside the real chat window.

Everything the layer must NOT disturb (routing, streaming, persistence, bubble
sizing, imports of the existing pipeline) is pinned here next to what it adds.
"""

from __future__ import annotations

import html
import re

import pytest

pytest.importorskip("pytestqt", reason="pytest-qt is required for GUI tests")

from PySide6.QtCore import Qt  # noqa: E402

from aashi.emotion import layer as layer_module  # noqa: E402
from aashi.emotion import phrases  # noqa: E402
from aashi.emotion.emotions import Emotion  # noqa: E402
from aashi.paths import resolve_paths  # noqa: E402
from aashi.storage.database import ConversationDatabase  # noqa: E402
from aashi.ui.components.chat_bubble import CHAT_BUBBLE_MAX_WIDTH_PX  # noqa: E402
from aashi.ui.services import local_ai  # noqa: E402
from aashi.ui.services.local_ai import is_complex  # noqa: E402
from aashi.ui.themes.manager import ThemeManager  # noqa: E402
from aashi.ui.windows import chat_window  # noqa: E402


class Model:
    """A stand-in for the AI backend: records prompts, returns a scripted reply."""

    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.reply = "Okay."

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.reply


@pytest.fixture
def model(monkeypatch) -> Model:
    stub = Model()
    monkeypatch.setattr(chat_window, "fetch_response_hybrid", stub)
    return stub


@pytest.fixture
def window(qtbot, tmp_path, monkeypatch, model):
    paths = resolve_paths(user_data_dir=tmp_path, bundle_root=tmp_path, config_dir=tmp_path)
    paths.ensure_user_directories()
    db = ConversationDatabase(paths)
    monkeypatch.setattr(chat_window, "resolve_paths", lambda: paths)
    monkeypatch.setattr(chat_window, "get_database", lambda _p=None: db)
    win = chat_window.AashiChatWindow(ThemeManager())
    qtbot.addWidget(win)
    win.show()
    yield win
    win._finish_typewriter()
    db.close()


def say(window, qtbot, text: str) -> None:
    """Send ``text`` and wait for the reply to finish typing."""
    before = window.message_count
    window.input.setText(text)
    qtbot.keyClick(window.input, Qt.Key.Key_Return)
    qtbot.waitUntil(
        lambda: window.message_count == before + 2
        and window._typewriter_bubble is None
        and window._thinking_bubble is None,
        timeout=8000,
    )
    window._finish_typewriter()


def last_reply_html(window) -> str:
    return window._messages[-1].text


def stored(window) -> list[tuple[str, str]]:
    repo = window._ensure_repository()
    return [(m["role"], m["content"]) for m in repo.get_messages(window._conversation_id)]


# ── 8. "hi" is natural: no thinking, no preamble, right name ───────────────────────────


def test_hi_gets_a_short_greeting_with_no_thinking_bubble_or_preamble(window, model, qtbot) -> None:
    model.reply = "Wait, let me think... Heyy Ansh! How's your day going?"
    window.input.setText("hi")
    qtbot.keyClick(window.input, Qt.Key.Key_Return)
    assert window._thinking_bubble is None  # no "thinking" moment for a greeting
    qtbot.waitUntil(lambda: window.message_count == 2 and window._typewriter_bubble is None, timeout=8000)
    window._finish_typewriter()

    assert html.unescape(last_reply_html(window)) == "Heyy Kartik! How's your day going?"
    assert stored(window)[-1] == ("assistant", "Heyy Kartik! How's your day going?")
    assert "Ansh" not in last_reply_html(window)
    # The model was asked for a casual, preamble-free greeting.
    assert "no preamble" in model.prompts[0] and "Kartik" in model.prompts[0]


# ── 1 & 9. technical questions are completely unchanged ──────────────────────────────────


def test_technical_question_reaches_the_model_byte_for_byte_as_before(window, model, qtbot) -> None:
    model.reply = "A decorator wraps a function.\n\n```python\n@timer\ndef f(): ...\n```"
    say(window, qtbot, "Explain Python decorators.")
    assert model.prompts == ["User: Explain Python decorators."]  # exactly the pre-emotion prompt
    assert stored(window)[-1] == ("assistant", model.reply)  # and the reply is stored untouched


def test_emotion_does_not_alter_the_factual_reply(window, model, qtbot) -> None:
    facts = "The answer is 42. Run `pip install x==1.2.3` and see https://example.com/a?b=1&c=2."
    model.reply = facts
    say(window, qtbot, "I finally fixed the bug!")
    html = last_reply_html(window)
    for fact in ("42", "pip install x==1.2.3", "https://example.com/a?b=1&amp;c=2"):
        assert fact in html


# ── expressive contexts get a tone, and the note never leaks into storage ───────────────


@pytest.mark.parametrize(
    ("message", "tone"),
    [
        ("I'm feeling really stressed.", "reassuring"),
        ("I finally fixed the bug!", "excited"),
        ("You're useless 😂", "playful"),
        ("I'm studying for my exam, help me with recursion", "teacher"),
        ("That's wrong, you made a mistake.", "mistake"),
        ("I'm so tired today", "caring"),
    ],
)
def test_expressive_messages_carry_a_style_note(window, model, qtbot, message: str, tone: str) -> None:
    say(window, qtbot, message)
    prompt = model.prompts[0]
    assert "(Aashi:" in prompt
    assert tone in prompt.lower()
    assert is_complex(prompt) == is_complex(f"User: {message}")  # routing preserved


def test_style_notes_are_never_stored_or_replayed(window, model, qtbot) -> None:
    say(window, qtbot, "hi")
    say(window, qtbot, "I'm stressed")
    assert all("(Aashi:" not in content and "Style note" not in content for _, content in stored(window))
    assert all("(Aashi:" not in turn["content"] for turn in window._chat_history)
    assert "(Aashi:" not in window._build_history_prompt()


def test_routing_is_preserved_on_every_turn_as_history_grows(window, model, qtbot) -> None:
    """Whatever size the note takes (or none), the prompt routes as it would have."""
    for message in ("hi", "I'm stressed", "ok thanks", "I finally fixed it!"):
        say(window, qtbot, message)
    for prompt in model.prompts:
        base = prompt.rsplit("\n\n(Aashi:", 1)[0] if "(Aashi:" in prompt else prompt
        assert is_complex(prompt) == is_complex(base)
    assert "(Aashi:" in model.prompts[0]  # short prompts still get a note when one fits


def test_when_no_note_fits_the_opener_still_carries_the_mood(window, model, qtbot) -> None:
    for message in ("hi", "I'm stressed", "ok thanks"):
        say(window, qtbot, message)
    model.reply = "Okay."
    say(window, qtbot, "I finally fixed it!")
    assert "(Aashi:" not in model.prompts[-1]  # the prompt was already near the routing line
    visible = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", last_reply_html(window))).split())
    assert visible.endswith("Okay.") and visible != "Okay."  # one short excited opener was added
    assert any(o.replace("{name}", "Kartik") in visible for o in phrases.OPENERS[Emotion.EXCITED])


# ── temporary mood: carried for a few turns, cleared on a new chat ───────────────────────


def test_stress_is_carried_briefly_then_cleared_by_a_new_chat(window, model, qtbot) -> None:
    say(window, qtbot, "I'm so stressed today")
    say(window, qtbot, "how do I reverse a list in python")
    assert "(Aashi:" in model.prompts[1] and "calm" in model.prompts[1].lower()

    window._on_new_chat_requested()
    say(window, qtbot, "how do I reverse a list in python")
    assert model.prompts[2] == "User: how do I reverse a list in python"  # nothing carried over


def test_the_carried_mood_is_not_saved_to_the_database(window, model, qtbot) -> None:
    say(window, qtbot, "I'm so stressed today")
    texts = " ".join(content for _, content in stored(window))
    assert "stressed today" in texts  # the user's own words are history, as always
    assert "carried" not in texts.lower() and "current_context" not in texts


# ── fallback opener ────────────────────────────────────────────────────────────────────


def test_opener_is_added_only_when_no_note_fits(window, model, qtbot) -> None:
    message = "I'm so stressed about everything going on with my exams and the assignments today, can't focus"
    model.reply = "Let's slow down. Breathe first, then list the tasks."
    say(window, qtbot, message)
    assert model.prompts == [f"User: {message}"]  # no note could ride along: prompt unchanged
    html = last_reply_html(window)
    assert "Breathe first, then list the tasks." in html  # the reply itself is kept as written
    assert any(
        o.replace("{name}", "Kartik") in html or o.replace("{name}", "Kartik").replace("'", "&#x27;") in html
        for o in phrases.OPENERS[Emotion.COMFORTING]
    )


# ── 10. existing systems are untouched ───────────────────────────────────────────────────


def test_existing_pipeline_wiring_is_unchanged() -> None:
    assert chat_window.fetch_response_hybrid is local_ai.fetch_response_hybrid
    assert local_ai.MODE == "hybrid"
    assert chat_window._TYPEWRITER_CHARS_PER_TICK == 1
    assert chat_window._TYPEWRITER_INTERVAL_MS == 30
    assert chat_window._TYPEWRITER_MAX_TICKS == 220
    assert CHAT_BUBBLE_MAX_WIDTH_PX == 640


def test_streaming_still_reveals_the_reply_progressively(window, model, qtbot) -> None:
    model.reply = "Heyy Kartik! Kaise ho aaj? Sab theek hai na?"
    window.input.setText("hi")
    qtbot.keyClick(window.input, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: window._typewriter_bubble is not None, timeout=8000)
    bubble = window._typewriter_bubble
    seen = {bubble.text}
    qtbot.waitUntil(lambda: window._typewriter_bubble is None, timeout=8000)
    seen.add(bubble.text)
    assert bubble.text == model.reply
    assert len(model.reply) > len(min(seen, key=len))  # it started shorter than the final text


def test_layer_hooks_do_not_run_for_image_and_document_paths(window, model, qtbot, monkeypatch) -> None:
    """Vision and PDF/DOCX replies keep their own prompt; only the plain-text path is wrapped."""
    calls: list[str] = []
    monkeypatch.setattr(window._emotion, "prepare", lambda p, m: calls.append(m) or layer_module.Prepared(p, window._emotion.analyse(m)))
    sent: list[str] = []
    monkeypatch.setattr(window, "_request_vision_reply", lambda message, path: sent.append(message))
    monkeypatch.setattr(window, "_clear_attachment", lambda: None)
    window._selected_file = "/tmp/picture.png"
    window.input.setText("I'm stressed, what is in this image?")
    window._submit_message()
    assert calls == []  # prepare() was never consulted
    assert sent and "(Aashi:" not in sent[0]


def test_disabled_layer_changes_nothing(window, model, qtbot, monkeypatch) -> None:
    monkeypatch.setattr(layer_module, "EMOTION_LAYER_ENABLED", False)
    model.reply = "Hello Ansh"
    say(window, qtbot, "hi")
    assert model.prompts == ["User: hi"]
    assert stored(window)[-1] == ("assistant", "Hello Ansh")  # untouched, as before the layer existed
