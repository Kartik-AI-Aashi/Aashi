"""Tests for automatic conversation titles (Qt-free)."""

from __future__ import annotations

import pytest

from aashi.ui.services import titles
from aashi.ui.services.titles import MAX_TITLE_CHARS, clean_title, fetch_ai_title, heuristic_title


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Can you explain how a binary search works?", "How a Binary Search Works"),
        ("what is the capital of france", "Capital of France"),
        ("how do i center a div in css", "Center a Div in Css"),
        ("please help me plan a 5 day trip to Goa in december", "Plan a 5 Day Trip"),
        ("tell me about the iPhone 15", "iPhone 15"),
        ("what is a binary tree", "Binary Tree"),
    ],
)
def test_heuristic_strips_filler_and_names_the_topic(question: str, expected: str) -> None:
    assert heuristic_title(question) == expected


def test_heuristic_keeps_a_one_word_message() -> None:
    assert heuristic_title("hi") == "Hi"


def test_heuristic_ignores_the_attachment_label_line() -> None:
    assert heuristic_title("summarize this report\n📎 report.pdf") == "Summarize This Report"


def test_heuristic_never_exceeds_the_cap_and_never_ends_on_a_small_word() -> None:
    title = heuristic_title("Compare React vs Vue for a large dashboard application")
    assert len(title) <= MAX_TITLE_CHARS
    assert title.split()[-1].lower() not in {"a", "the", "of", "to", "for", "vs"}


def test_heuristic_falls_back_when_empty() -> None:
    assert heuristic_title("   ") == "New chat"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('"Binary Search Explained"', "Binary Search Explained"),
        ("Title: Trip Plan for Goa.", "Trip Plan for Goa"),
        ("**Goa Trip**\nsome extra explanation", "Goa Trip"),
    ],
)
def test_clean_title_sanitises_model_replies(raw: str, expected: str) -> None:
    assert clean_title(raw) == expected


@pytest.mark.parametrize(
    "raw", ["", "Something went wrong", "I'm sorry, I cannot do that for you right now ok"]
)
def test_clean_title_rejects_unusable_replies(raw: str) -> None:
    assert clean_title(raw) is None


def test_fetch_ai_title_uses_the_backend_and_cleans_the_reply(monkeypatch) -> None:
    monkeypatch.setattr(titles, "AI_TITLES_ENABLED", True)
    seen: dict[str, str] = {}

    def fake(prompt: str) -> str:
        seen["prompt"] = prompt
        return '"Binary Search Basics"'

    monkeypatch.setattr(titles.local_ai, "fetch_response_hybrid", fake)
    assert fetch_ai_title("how does binary search work") == "Binary Search Basics"
    assert "how does binary search work" in seen["prompt"]


def test_fetch_ai_title_returns_none_on_failure(monkeypatch) -> None:
    monkeypatch.setattr(titles, "AI_TITLES_ENABLED", True)

    def boom(_prompt: str) -> str:
        raise RuntimeError("offline")

    monkeypatch.setattr(titles.local_ai, "fetch_response_hybrid", boom)
    assert fetch_ai_title("anything") is None


def test_fetch_ai_title_is_skipped_when_disabled(monkeypatch) -> None:
    monkeypatch.setattr(titles, "AI_TITLES_ENABLED", False)
    monkeypatch.setattr(
        titles.local_ai, "fetch_response_hybrid", lambda _p: pytest.fail("must not be called")
    )
    assert fetch_ai_title("anything") is None
