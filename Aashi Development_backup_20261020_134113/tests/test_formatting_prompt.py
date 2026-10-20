"""Verify the response-formatting instructions shipped to every model backend.

The formatting rules live in :data:`FORMATTING_PROMPT` and are composed into
:data:`SYSTEM_PROMPT`, which is what every backend actually sends — OpenRouter
text, OpenRouter vision, and the local Ollama model. These tests pin the
behaviour the user cares about: the model is told *when* to produce a text
diagram, how to draw each supported format, and — just as importantly — that
ordinary questions must NOT be turned into diagrams.
"""

from __future__ import annotations

from aashi.ui.services.openrouter import FORMATTING_PROMPT, SYSTEM_PROMPT


def test_formatting_rules_are_part_of_the_system_prompt() -> None:
    assert "RESPONSE FORMATTING RULES" in SYSTEM_PROMPT


def test_identity_rules_are_preserved() -> None:
    assert "STRICT IDENTITY RULES" in SYSTEM_PROMPT
    assert 'Your name is ALWAYS "Aashi".' in SYSTEM_PROMPT


def test_identity_rules_come_first() -> None:
    assert SYSTEM_PROMPT.index("STRICT IDENTITY RULES") < SYSTEM_PROMPT.index(
        "RESPONSE FORMATTING RULES"
    )


def test_structure_detection_keywords_are_listed() -> None:
    prompt = FORMATTING_PROMPT.lower()
    for keyword in (
        "flowchart",
        "workflow",
        "process",
        "diagram",
        "architecture",
        "pipeline",
        "decision tree",
        "hierarchy",
        "visualize",
        "show the steps",
    ):
        assert keyword in prompt, f"missing structure keyword: {keyword}"


def test_flowchart_format_specifies_box_drawing_chars() -> None:
    for char in ("│", "▼", "├──", "└──"):
        assert char in FORMATTING_PROMPT


def test_decision_tree_format_specifies_branching() -> None:
    assert "┌───┴───┐" in FORMATTING_PROMPT
    assert "YES / NO" in FORMATTING_PROMPT


def test_architecture_format_specifies_merging() -> None:
    assert "└───┬───┘" in FORMATTING_PROMPT


def test_monospace_alignment_is_requested() -> None:
    assert "monospace" in FORMATTING_PROMPT.lower()


def test_normal_questions_must_stay_normal() -> None:
    assert "ONLY when the user asks" in FORMATTING_PROMPT
    assert "forced flowchart" in FORMATTING_PROMPT


def test_markdown_structure_is_encouraged() -> None:
    assert "Markdown" in FORMATTING_PROMPT
    assert "headings" in FORMATTING_PROMPT.lower()


def test_instruction_is_not_a_hardcoded_answer() -> None:
    # The prompt must request a FORMAT, never supply the scientific content.
    assert "photosynthesis" not in FORMATTING_PROMPT.lower()
    assert "chlorophyll" not in FORMATTING_PROMPT.lower()
