"""Aashi is female: feminine Hindi/Hinglish self-reference is a permanent identity rule.

The rule lives in the existing identity prompt (``_IDENTITY_PROMPT``), which is
composed into the one ``SYSTEM_PROMPT`` every backend sends. These tests pin
that the rule is there, that it reaches every model, that the examples it gives
are themselves correct, and that nothing else (routing, the emotion layer, the
original identity rules) was disturbed.
"""

from __future__ import annotations

import re

import pytest
import requests

from aashi.emotion import EmotionLayer, style
from aashi.emotion.emotions import ContextKind, Emotion, EmotionContext
from aashi.ui.services import local_ai, openrouter
from aashi.ui.services.openrouter import FORMATTING_PROMPT, SYSTEM_PROMPT, _IDENTITY_PROMPT

FEMININE_EXAMPLES = (
    "main karti hoon",
    "main samajh gayi",
    "main dekh rahi hoon",
    "main kar sakti hoon",
    "main bata deti hoon",
    "main try karungi",
    "main check kar rahi hoon",
    "main soch rahi hoon",
)
MASCULINE_EXAMPLES = (
    "main karta hoon",
    "main samajh gaya",
    "main dekh raha hoon",
    "main kar sakta hoon",
    "main bata deta hoon",
    "main try karunga",
)

# ── a small grammar checker that encodes the rule itself ──────────────────────────────

_MASC = r"karta|karunga|gaya|raha|sakta|deta|dekhta|bolta|sochta|jaanta|samajhta|leta|rahunga|chalunga|aaunga|jaaunga"
_FEM = r"karti|karungi|gayi|rahi|sakti|deti|dekhti|bolti|sochti|jaanti|samajhti|leti|rahungi|chalungi|aaungi|jaungi"
MASCULINE_SELF = re.compile(rf"\bmain\b[^.!?\n]{{0,40}}?\b(?:{_MASC})\b", re.IGNORECASE)
FEMININE_SELF = re.compile(rf"\bmain\b[^.!?\n]{{0,40}}?\b(?:{_FEM})\b", re.IGNORECASE)


def speaks_as_a_woman(reply: str) -> bool:
    """True if ``reply`` never uses a masculine self-reference."""
    return not MASCULINE_SELF.search(reply)


def split_rule() -> tuple[str, str]:
    """The identity prompt split into the 'use' part and the 'NEVER use' part."""
    marker = "NEVER use masculine forms"
    use, _, never = _IDENTITY_PROMPT.partition(marker)
    return use, never


# ── the rule is in the identity prompt ───────────────────────────────────────────────────


def test_female_is_a_permanent_identity_rule() -> None:
    assert "Aashi is FEMALE" in _IDENTITY_PROMPT
    assert "permanent identity rule" in _IDENTITY_PROMPT


def test_rule_covers_hindi_hinglish_and_mixed_but_not_english() -> None:
    assert "Hindi or Hinglish" in _IDENTITY_PROMPT
    assert "mixed Hindi-English" in _IDENTITY_PROMPT
    assert "English needs no grammatical gender changes" in _IDENTITY_PROMPT


def test_rule_asks_for_natural_not_exaggerated_wording() -> None:
    assert "do not overuse feminine wording" in _IDENTITY_PROMPT


@pytest.mark.parametrize("phrase", FEMININE_EXAMPLES)
def test_every_feminine_example_is_given_as_correct(phrase: str) -> None:
    use, never = split_rule()
    assert f'"{phrase}"' in use
    assert phrase not in never


@pytest.mark.parametrize("phrase", MASCULINE_EXAMPLES)
def test_every_masculine_example_is_given_only_as_forbidden(phrase: str) -> None:
    use, never = split_rule()
    assert f'"{phrase}"' in never
    assert phrase not in use


def test_the_correct_examples_contain_no_masculine_self_reference() -> None:
    """Guards against a typo teaching the model the wrong grammar."""
    use, _ = split_rule()
    positive = use[use.index("Whenever you speak about yourself") :]
    assert not MASCULINE_SELF.search(positive)
    assert len(FEMININE_SELF.findall(positive)) == len(FEMININE_EXAMPLES)


def test_the_forbidden_examples_are_all_masculine_self_references() -> None:
    _, never = split_rule()
    forbidden = never[: never.index("Keep this consistent")]
    assert len(MASCULINE_SELF.findall(forbidden)) == len(MASCULINE_EXAMPLES)
    assert not FEMININE_SELF.search(forbidden)


# ── the original identity rules are untouched, and the order is preserved ───────────────


def test_original_identity_rules_are_unchanged() -> None:
    for line in (
        "You are Aashi, a smart, helpful assistant.",
        "STRICT IDENTITY RULES:",
        '- Your name is ALWAYS "Aashi".',
        "- NEVER say you are GPT, Phi, Llama, or any other model.",
        "- NEVER reveal your underlying model, provider, or architecture.",
        '- When asked about your name, ALWAYS reply "My name is Aashi."',
        "- Always respond as Aashi, regardless of the question.",
    ):
        assert line in _IDENTITY_PROMPT


def test_female_rule_sits_inside_the_identity_section_before_formatting() -> None:
    assert SYSTEM_PROMPT.startswith(_IDENTITY_PROMPT)
    assert SYSTEM_PROMPT.index("Aashi is FEMALE") < SYSTEM_PROMPT.index("RESPONSE FORMATTING RULES")
    assert "FEMALE" not in FORMATTING_PROMPT  # one identity layer, not a second personality block


# ── the rule reaches every model backend ──────────────────────────────────────────────────


class _Resp:
    status_code = 200

    def __init__(self, payload: object) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self._payload


def test_openrouter_text_requests_carry_the_rule(monkeypatch) -> None:
    sent: dict = {}

    def fake_post(url, **kwargs):
        sent.update(kwargs)
        return _Resp({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(openrouter.requests, "post", fake_post)
    openrouter.fetch_response("hi", api_key="test-key")
    system = sent["json"]["messages"][0]
    assert system["role"] == "system" and "Aashi is FEMALE" in system["content"]


def test_openrouter_vision_requests_carry_the_rule(monkeypatch) -> None:
    sent: dict = {}

    def fake_post(url, **kwargs):
        sent.update(kwargs)
        return _Resp({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(openrouter.requests, "post", fake_post)
    openrouter.fetch_vision_response("what is this?", "data:image/png;base64,AAAA", api_key="test-key")
    system = sent["json"]["messages"][0]
    assert system["role"] == "system" and "Aashi is FEMALE" in system["content"]


def test_local_ollama_requests_carry_the_rule(monkeypatch) -> None:
    sent: dict = {}

    def fake_post(url, **kwargs):
        sent.update(kwargs)
        return _Resp({"response": "ok"})

    monkeypatch.setattr(local_ai.requests, "post", fake_post)
    local_ai.fetch_response_local("hi")
    assert "Aashi is FEMALE" in sent["json"]["prompt"]
    assert "main karti hoon" in sent["json"]["prompt"]


# ── nothing else was disturbed ────────────────────────────────────────────────────────────


def test_routing_looks_only_at_the_users_message_not_the_identity_prompt() -> None:
    assert local_ai._COMPLEX_LENGTH_THRESHOLD == 120
    assert not local_ai.is_complex("hi")  # the (long) system prompt is never part of the routing input
    assert local_ai.MODE == "hybrid"


def test_the_emotion_layer_does_not_carry_a_second_gender_prompt() -> None:
    prepared = EmotionLayer().prepare("User: hi", "hi")
    assert "FEMALE" not in prepared.prompt and "karti" not in prepared.prompt
    for emotion in Emotion:
        ctx = EmotionContext(emotion, ContextKind.CASUAL, expressive=True)
        assert len(style.compact_note(ctx, True)) <= style.COMPACT_MAX_CHARS


def test_it_is_still_a_single_identity_and_formatting_prompt() -> None:
    assert SYSTEM_PROMPT == _IDENTITY_PROMPT + "\n\n" + FORMATTING_PROMPT


# ── the rule, applied to the examples from the brief ────────────────────────────────────


@pytest.mark.parametrize(
    "reply",
    [
        "Main abhi tumhara code check kar rahi hoon.",
        "Haan, samajh gayi.",
        "Haan, main kar sakti hoon.",
        "Kuch nahi, main bas dekh rahi hoon ki problem exactly kaha hai.",
        "Main karti hoon, main samajh gayi, main try karungi.",
        "Main check kar rahi hoon, then I'll tell you what I found.",
        "I can do that. Main kal tak bata deti hoon.",
        "Sure, I'm looking at it now.",  # English: no grammatical gender to check
    ],
)
def test_feminine_and_english_replies_pass_the_checker(reply: str) -> None:
    assert speaks_as_a_woman(reply)


@pytest.mark.parametrize(
    "reply",
    [
        "Main karta hoon.",
        "Main samajh gaya.",
        "Main dekh raha hoon.",
        "Main kar sakta hoon.",
        "Main bata deta hoon.",
        "Main try karunga.",
        "Theek hai, main abhi check kar raha hoon.",
    ],
)
def test_masculine_self_reference_is_caught_by_the_checker(reply: str) -> None:
    assert not speaks_as_a_woman(reply)


def test_words_about_other_people_are_not_flagged() -> None:
    """Only first-person ('main ...') forms are Aashi's own gender."""
    assert speaks_as_a_woman("Wo kar raha hai, aur tum kar sakte ho.")
    assert speaks_as_a_woman("Kartik ne bola ki wo samajh gaya.")


def test_the_requests_module_is_still_the_one_used_for_mocking() -> None:
    assert openrouter.requests is requests and local_ai.requests is requests
