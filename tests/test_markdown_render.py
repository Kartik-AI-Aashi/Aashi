"""Verify the markdown-to-HTML renderer for the chat bubble.

The renderer converts fenced code blocks to ``<pre>`` HTML so the
:class:`QLabel` RichText engine preserves whitespace alignment (critical for
flowcharts and ASCII diagrams), while HTML-escaping all other content to
prevent injection.

This module is Qt-free — the ``<pre>`` preservation is a standard HTML
behaviour confirmed empirically against the same Qt offscreen label the
chat bubble uses.
"""

from __future__ import annotations

from aashi.ui.services.markdown_render import render_markdown


# ── plain text passthrough ─────────────────────────────────────────────────


def test_plain_text_without_code_fences_passes_through() -> None:
    assert render_markdown("Hello world") == "Hello world"


def test_empty_string_returns_empty() -> None:
    assert render_markdown("") == ""


def test_html_characters_are_escaped_outside_code() -> None:
    assert render_markdown("a < b & c > d") == "a &lt; b &amp; c &gt; d"


def test_newlines_are_preserved_outside_code() -> None:
    result = render_markdown("line one\n\nline two")
    assert result == "line one\n\nline two"


def test_single_angle_bracket_is_not_an_html_tag() -> None:
    assert render_markdown("a < b") == "a &lt; b"


# ── fenced code blocks ─────────────────────────────────────────────────────


def test_code_fence_converted_to_pre() -> None:
    text = "```text\ncode\n```"
    assert render_markdown(text) == "<pre>code</pre>"


def test_code_fence_without_language_tag() -> None:
    text = "```\ncode\n```"
    assert render_markdown(text) == "<pre>code</pre>"


def test_code_fence_strips_language_tag() -> None:
    text = "```python\nprint('hi')\n```"
    result = render_markdown(text)
    assert "python" not in result
    assert "<pre>print(&#x27;hi&#x27;)</pre>" == result


def test_leading_whitespace_is_preserved_in_code_block() -> None:
    text = "```text\n        Start\n          |\n          v\n```"
    result = render_markdown(text)
    assert "        Start" in result
    assert "          |" in result
    assert "          v" in result


def test_trailing_newline_before_closing_fence_is_stripped() -> None:
    text = "```text\ncode\n\n```"
    result = render_markdown(text)
    assert result == "<pre>code</pre>"


def test_code_content_html_is_escaped() -> None:
    text = "```text\n<b>bold</b>\n```"
    result = render_markdown(text)
    assert "&lt;b&gt;bold&lt;/b&gt;" in result


def test_empty_code_block() -> None:
    text = "```text\n```"
    assert render_markdown(text) == "<pre></pre>"


def test_multiline_code_block() -> None:
    text = "```text\nline1\nline2\nline3\n```"
    result = render_markdown(text)
    assert result == "<pre>line1\nline2\nline3</pre>"


# ── mixed content ──────────────────────────────────────────────────────────


def test_text_before_and_after_code_block() -> None:
    text = "Before\n\n```text\ncode\n```\n\nAfter"
    result = render_markdown(text)
    assert result == "Before\n\n<pre>code</pre>\n\nAfter"


def test_text_outside_code_is_html_escaped() -> None:
    text = "<script>alert('x')</script>\n\n```text\ncode\n```\n\nDone."
    result = render_markdown(text)
    assert "&lt;script&gt;" in result.split("<pre>")[0]
    assert "<pre>code</pre>" in result


def test_multiple_code_blocks() -> None:
    text = "A\n\n```text\nblock1\n```\n\nB\n\n```text\nblock2\n```\n\nC"
    result = render_markdown(text)
    assert result.count("<pre>") == 2
    assert result.count("</pre>") == 2
    assert "<pre>block1</pre>" in result
    assert "<pre>block2</pre>" in result
    assert "A" in result.split("<pre>")[0]
    assert "B" in result.split("</pre>")[1].split("<pre>")[0]
    assert "C" in result.split("</pre>")[-1]


def test_code_fence_at_start_of_text() -> None:
    text = "```text\ncode\n```\n\nAfter"
    result = render_markdown(text)
    assert result.startswith("<pre>code</pre>")


def test_code_fence_at_end_of_text() -> None:
    text = "Before\n\n```text\ncode\n```"
    result = render_markdown(text)
    assert result.endswith("<pre>code</pre>")


def test_flowchart_leading_spaces_preserved() -> None:
    """The critical regression test: flowchart alignment must survive rendering."""
    text = (
        "Here is the process:\n\n"
        "```text\n"
        "        Start\n"
        "          |\n"
        "          v\n"
        "   Sunlight Absorption\n"
        "          |\n"
        "          v\n"
        "     Photosynthesis\n"
        "```\n\n"
        "Done."
    )
    result = render_markdown(text)
    # The intro text is HTML-escaped
    assert "Here is the process:" in result.split("<pre>")[0]
    # The code block preserves alignment
    pre_block = result.split("<pre>")[1].split("</pre>")[0]
    assert "        Start" in pre_block
    assert "          |" in pre_block
    assert "          v" in pre_block
    assert "   Sunlight Absorption" in pre_block
    # The outro text is HTML-escaped
    assert "Done." in result.split("</pre>")[-1]


def test_raw_text_without_fence_preserves_structure() -> None:
    """Plain text with newlines passes through unchanged (QLabel handles \\n)."""
    text = "line1\nline2\nline3"
    assert render_markdown(text) == text
