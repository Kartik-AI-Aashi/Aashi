"""Casual chat reads like a person texting; explanations keep their structure."""

from __future__ import annotations

import html
import re

import pytest

pytest.importorskip("pytestqt", reason="pytest-qt is required for GUI tests")

from PySide6.QtCore import Qt  # noqa: E402

from aashi.emotion import EmotionLayer, Session, detect, style  # noqa: E402
from aashi.emotion.emotions import ContextKind, Emotion, EmotionContext  # noqa: E402
from aashi.emotion.plain import plainify  # noqa: E402
from aashi.paths import resolve_paths  # noqa: E402
from aashi.storage.database import ConversationDatabase  # noqa: E402
from aashi.ui.services.openrouter import FORMATTING_PROMPT, SYSTEM_PROMPT  # noqa: E402
from aashi.ui.themes.manager import ThemeManager  # noqa: E402
from aashi.ui.windows import chat_window  # noqa: E402

# The model reply from the user's screenshot: gossip dressed up as a report.
ROBOTIC_REPLY = """## Response ✨
- **Direct Answer:** Main tumhare saath baat kar rhi hoon, Kartik! 😊

### Kyon Hai Ajeeb Lag Raha? 🤔
- Technology ki duniya mein kuch bhi possible hai!
- Main aapki help ke liye hamesha ready hoon, bina thake.

### Aage Kya? 🚀
- Batao, aaj kya help chahiye?

Takeaway: Just here to make your day easier! ✨"""

STRUCTURE_MARKERS = (r"^\s*#", r"^\s*[-*•]\s", r"\*\*", r"^\s*\d+[.)]\s", r"\b(?:Direct Answer|Takeaway)\b", r"^\s*Response\b")


def has_structure(text: str) -> bool:
    return any(re.search(p, text, re.MULTILINE) for p in STRUCTURE_MARKERS)


# ── the prompt no longer says "structure every answer" ────────────────────────────────


def test_prompt_has_a_casual_chat_mode_that_forbids_report_formatting() -> None:
    prompt = FORMATTING_PROMPT
    assert "CASUAL CHAT" in prompt
    assert "texting a friend" in prompt
    for banned in ("NO headings", "NO bullet points", "NO bold", "Response", "Direct Answer", "Takeaway"):
        assert banned in prompt


def test_prompt_no_longer_forces_structure_on_every_answer() -> None:
    assert "Structure every answer" not in FORMATTING_PROMPT
    assert "one-line takeaway" not in FORMATTING_PROMPT
    assert "EXPLANATIONS" in FORMATTING_PROMPT  # structure is kept, for explanations
    assert "RESPONSE FORMATTING RULES" in SYSTEM_PROMPT


# ── detection: the user's own messages are plain chat; real requests are not ────────────


@pytest.mark.parametrize(
    "message",
    [
        "ye kaise baat kar rhi ho?",
        "ye direct likho na ye aise kaise likh rhi ho response fir takeaway aur ye sab",
        "hi",
        "what are you doing",
        "why are you like this",
        "tum kya kar rahi ho abhi",
        "arre yaar bore ho raha hu",
        "I miss talking to you lol",
    ],
)
def test_everyday_chat_is_plain(message: str) -> None:
    ctx = detect(message, Session())
    assert ctx.plain and ctx.expressive


@pytest.mark.parametrize(
    "message",
    [
        "Explain Python decorators.",
        "explain how photosynthesis works",
        "how do I reverse a list in python",
        "what is the capital of france",
        "what time is it in Tokyo",
        "Summarize this document",
        "give me the main points of this",
        "difference between TCP and UDP",
        "write a function to sort a list",
        "compare React and Vue",
        "show me the steps to install docker",
        "make a flowchart of login",
        "translate this to hindi",
    ],
)
def test_explanations_and_requests_are_not_forced_plain(message: str) -> None:
    assert not detect(message, Session()).plain


def test_study_help_keeps_its_structure() -> None:
    ctx = detect("I'm studying for my exam, can you teach me recursion?", Session())
    assert ctx.emotion == Emotion.TEACHER and not ctx.plain


def test_a_technical_frustration_still_gets_structured_help() -> None:
    assert not detect("I'm so frustrated, my python code keeps throwing an error", Session()).plain


def test_emotional_chat_is_plain() -> None:
    for message in ("I'm feeling really stressed.", "I failed my exam today", "I'm so tired today", "I finally fixed the bug!"):
        assert detect(message, Session()).plain, message


# ── plainify ──────────────────────────────────────────────────────────────────────────


def test_the_screenshot_reply_loses_all_headings_bullets_bold_and_labels() -> None:
    out = plainify(ROBOTIC_REPLY)
    assert not has_structure(out), out
    assert "Main tumhare saath baat kar rhi hoon, Kartik! 😊" in out
    assert "Just here to make your day easier! ✨" in out


def test_every_sentence_survives() -> None:
    out = plainify(ROBOTIC_REPLY)
    for sentence in (
        "Technology ki duniya mein kuch bhi possible hai!",
        "Main aapki help ke liye hamesha ready hoon, bina thake.",
        "Batao, aaj kya help chahiye?",
    ):
        assert sentence in out


def test_bold_italic_and_numbered_markers_are_removed_but_words_stay() -> None:
    out = plainify("1. **Pehle** ye karo\n2. Phir *wo* karo\n\n__Done__")
    assert out == "Pehle ye karo\nPhir wo karo\n\nDone"


def test_a_label_prefix_is_removed_but_the_sentence_is_kept() -> None:
    assert plainify("**Takeaway:** Fixed! Ab seedha bolungi.") == "Fixed! Ab seedha bolungi."
    assert plainify("Direct Answer: haan bolo") == "haan bolo"


def test_the_word_response_inside_a_sentence_is_untouched() -> None:
    sentence = "Mera response thoda slow tha, sorry yaar."
    assert plainify(sentence) == sentence


def test_code_blocks_and_tables_are_never_touched() -> None:
    code = "## Fix\n\n```python\nx = 1\n```\n- done"
    table = "| a | b |\n|---|---|\n| 1 | 2 |"
    assert plainify(code) == code
    assert plainify(table) == table


def test_plainify_is_idempotent_and_never_returns_empty() -> None:
    once = plainify(ROBOTIC_REPLY)
    assert plainify(once) == once
    assert plainify("## Response") == "## Response"  # nothing but a label: keep the original


def test_facts_numbers_and_links_survive() -> None:
    text = "- The answer is 42, see https://example.com/a?b=1&c=2 (v3.12)."
    assert plainify(text) == "The answer is 42, see https://example.com/a?b=1&c=2 (v3.12)."


# ── the layer applies it to chat only ─────────────────────────────────────────────────


def test_layer_plainifies_a_casual_reply_but_not_an_explanation() -> None:
    layer = EmotionLayer()
    chat = layer.prepare("User: ye kaise baat kar rhi ho?", "ye kaise baat kar rhi ho?")
    assert not has_structure(layer.finish(ROBOTIC_REPLY, chat))

    explain = "## Decorators\n\n- They wrap functions\n- Use `@name`\n\n**Takeaway:** keep them small."
    tech = layer.prepare("User: Explain Python decorators.", "Explain Python decorators.")
    assert layer.finish(explain, tech) == explain  # untouched, exactly


def test_study_and_structured_requests_keep_their_headings() -> None:
    layer = EmotionLayer()
    reply = "## Recursion\n\n1. Base case\n2. Recursive case"
    for message in ("teach me recursion for my exam", "summarize this chapter"):
        prepared = layer.prepare(f"User: {message}", message)
        assert layer.finish(reply, prepared) == reply


def test_vision_and_document_replies_without_a_context_are_not_plainified() -> None:
    assert EmotionLayer().finish(ROBOTIC_REPLY) == ROBOTIC_REPLY.replace("Ansh", "Kartik")


# ── notes ─────────────────────────────────────────────────────────────────────────────


def test_plain_notes_ask_for_texting_style_and_stay_short() -> None:
    ctx = EmotionContext(Emotion.FRIENDLY, ContextKind.CASUAL, expressive=True, plain=True)
    assert "no headings, bullet points, bold" in style.full_note(ctx, True)
    compact = style.compact_note(ctx, True)
    assert "plain chat" in compact and len(compact) <= style.COMPACT_MAX_CHARS


def test_every_mood_keeps_its_compact_note_short_with_the_plain_tail() -> None:
    for emotion in Emotion:
        ctx = EmotionContext(emotion, ContextKind.CASUAL, expressive=True, plain=True)
        assert len(style.compact_note(ctx, True)) <= style.COMPACT_MAX_CHARS, emotion


# ── end to end in the real window ─────────────────────────────────────────────────────


@pytest.fixture
def window(qtbot, tmp_path, monkeypatch):
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


def _say(window, qtbot, text: str) -> None:
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


def _stored_assistant(window) -> str:
    repo = window._ensure_repository()
    return [m["content"] for m in repo.get_messages(window._conversation_id) if m["role"] == "assistant"][-1]


def test_gossip_reply_shows_as_plain_text_in_the_chat(window, qtbot, monkeypatch) -> None:
    monkeypatch.setattr(chat_window, "fetch_response_hybrid", lambda _p: ROBOTIC_REPLY)
    _say(window, qtbot, "ye kaise baat kar rhi ho?")
    shown = window._messages[-1].text
    assert "<li" not in shown and "<ul" not in shown and "font-weight:600" not in shown
    visible = html.unescape(re.sub(r"<[^>]+>", " ", shown))
    assert "Response" not in visible and "Takeaway" not in visible and "Direct Answer" not in visible
    assert "Main tumhare saath baat kar rhi hoon" in visible
    assert not has_structure(_stored_assistant(window))  # what is saved matches what is shown


def test_the_next_screenshot_message_also_gets_a_plain_reply(window, qtbot, monkeypatch) -> None:
    reply = '## Response ✨\n\n**Direct likhe deti hoon:**\n\n"Kartik, main simple tarike se baat kar rhi hoon!"\n\n**Takeaway:** Fixed!'
    monkeypatch.setattr(chat_window, "fetch_response_hybrid", lambda _p: reply)
    _say(window, qtbot, "ye direct likho na ye aise kaise likh rhi ho response fir takeaway aur ye sab")
    assert not has_structure(window._messages[-1].text.replace("<br>", "\n"))


def test_chat_prompt_asks_for_plain_texting(window, qtbot, monkeypatch) -> None:
    sent: list[str] = []
    monkeypatch.setattr(chat_window, "fetch_response_hybrid", lambda p: sent.append(p) or "Haan bolo!")
    _say(window, qtbot, "ye kaise baat kar rhi ho?")
    assert "plain chat" in sent[0]


def test_an_explanation_keeps_its_headings_and_lists(window, qtbot, monkeypatch) -> None:
    reply = "## Decorators\n\n- They wrap functions\n- They run at definition time\n\n**Takeaway:** keep them small."
    sent: list[str] = []
    monkeypatch.setattr(chat_window, "fetch_response_hybrid", lambda p: sent.append(p) or reply)
    _say(window, qtbot, "Explain Python decorators.")
    shown = window._messages[-1].text
    assert "<ul" in shown and "font-weight:600" in shown and "<b>Takeaway:</b>" in shown
    assert sent == ["User: Explain Python decorators."]  # and the prompt is untouched
    assert _stored_assistant(window) == reply
