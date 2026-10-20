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

from aashi.ui.services.markdown_render import render_markdown, tidy_reply


# ── plain text passthrough ─────────────────────────────────────────────────


def test_plain_text_without_code_fences_passes_through() -> None:
    assert render_markdown("Hello world") == "Hello world"


def test_empty_string_returns_empty() -> None:
    assert render_markdown("") == ""


def test_html_characters_are_escaped_outside_code() -> None:
    assert render_markdown("a < b & c > d") == "a &lt; b &amp; c &gt; d"


def test_blank_line_makes_separate_paragraphs() -> None:
    # A raw "\n\n" collapses to a space inside a rich-text QLabel, so paragraphs
    # must be explicit <p> blocks.
    result = render_markdown("line one\n\nline two")
    assert result.count("<p ") == 2
    assert "line one" in result and "line two" in result
    assert "\n" not in result


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
    assert "<pre>code</pre>" in result
    assert result.index("Before") < result.index("<pre>") < result.index("After")


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
    assert "<pre>code</pre>" in result
    assert result.index("<pre>") < result.index("After")


def test_code_fence_at_end_of_text() -> None:
    text = "Before\n\n```text\ncode\n```"
    result = render_markdown(text)
    assert "<pre>code</pre>" in result
    assert result.index("Before") < result.index("<pre>")


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


def test_single_newlines_become_line_breaks() -> None:
    """A lone "\\n" would collapse to a space in a QLabel; it must become <br>."""
    assert render_markdown("line1\nline2\nline3") == "line1<br>line2<br>line3"


# ── markdown structure ─────────────────────────────────────────────────────


def test_headings_render_bold_and_sized() -> None:
    result = render_markdown("## Quick rules\n\nbody")
    assert "Quick rules" in result and "font-weight:600" in result
    assert "##" not in result


def test_bold_italic_and_inline_code() -> None:
    result = render_markdown("a **bold** and *soft* and `code` word")
    assert "<b>bold</b>" in result
    assert "<i>soft</i>" in result
    assert ">code</code>" in result
    assert "**" not in result


def test_snake_case_is_not_italicised() -> None:
    assert "<i>" not in render_markdown("use snake_case_names and 2*3*4")


def test_markdown_inside_inline_code_is_not_rendered() -> None:
    result = render_markdown("see `**not bold**` here")
    assert "<b>" not in result
    assert "**not bold**" in result


def test_bullet_list() -> None:
    result = render_markdown("Intro:\n- one\n- two\n* three")
    assert result.count("<li") == 3
    assert "<ul" in result and "<ol" not in result


def test_numbered_list_keeps_its_start_number() -> None:
    result = render_markdown("3. third\n4. fourth")
    assert '<ol start="3"' in result
    assert result.count("<li") == 2


def test_nested_list_is_nested() -> None:
    result = render_markdown("1. parent\n   - child a\n   - child b\n2. next")
    assert result.count("<ul") == 1 and result.count("<ol") == 1
    # the child list sits inside the first <li>, before its closing tag
    assert result.index("<ul") < result.index("</li>")


def test_list_directly_after_paragraph_without_blank_line() -> None:
    result = render_markdown("Steps:\n1. first\n2. second")
    assert "Steps:" in result and result.count("<li") == 2


def test_blank_line_between_items_keeps_one_list() -> None:
    result = render_markdown("1. a\n\n2. b\n\n3. c")
    assert result.count("<ol") == 1 and result.count("<li") == 3


def test_table() -> None:
    result = render_markdown("| A | B |\n|---|---|\n| 1 | 2 |")
    assert "<table" in result
    assert result.count("<th>") == 2 and result.count("<td>") == 2


def test_quote_and_rule() -> None:
    result = render_markdown("> wise words\n\n---\n\nafter")
    assert "font-style:italic" in result and "wise words" in result
    assert "<hr>" in result


def test_links_only_allow_http() -> None:
    assert '<a href="https://x.dev">site</a>' in render_markdown("[site](https://x.dev)")
    assert "<a " not in render_markdown("[bad](javascript:alert(1))")


def test_html_is_escaped_everywhere() -> None:
    result = render_markdown("# <b>x</b>\n\n- <script>\n\n> <i>y</i>")
    assert "<script>" not in result
    assert "&lt;script&gt;" in result and "&lt;b&gt;" in result


def test_unterminated_code_fence_renders_as_code_while_streaming() -> None:
    result = render_markdown("Here:\n\n```python\nprint(1)")
    assert "<pre>print(1)</pre>" in result


def test_partial_markdown_never_crashes_or_leaks_tags() -> None:
    reply = "## Title\n\n1. **Bold item** with `code`\n   - sub\n\n| a | b |\n|---|---|\n| 1 | 2 |"
    for end in range(len(reply) + 1):
        out = render_markdown(reply[:end])
        assert "\x01" not in out and "\x00" not in out


def test_placeholder_text_inside_code_is_not_replaced() -> None:
    out = render_markdown("Intro\n\n```python\nx = f'{M} {H} {pre}'\n```\n\n# Next")
    assert "{M} {H} {pre}" in out


def test_control_characters_are_stripped() -> None:
    assert "\x00" not in render_markdown("a\x00b\x01c")


# ── tidy_reply: repairing walls of text ───────────────────────────────────


def test_tidy_puts_inline_numbered_items_on_their_own_lines() -> None:
    text = "Here is how: 1. Use headings. 2. Break content up. 3. Add emojis."
    assert tidy_reply(text) == "Here is how:\n1. Use headings.\n2. Break content up.\n3. Add emojis."


def test_tidy_handles_two_separate_numbered_runs() -> None:
    text = "A: 1. a 2. b **Example**: 1. x 2. y 3. z"
    lines = tidy_reply(text).split("\n")
    assert [ln[:2] for ln in lines if ln[:1].isdigit()] == ["1.", "2.", "1.", "2.", "3."]


def test_tidy_leaves_a_stray_number_alone() -> None:
    text = "I bought 2. Then left. Version 3. is out."
    assert tidy_reply(text) == text


def test_tidy_moves_inline_headings_and_bullets_to_new_lines() -> None:
    out = tidy_reply("Sure thing! ### Example Structure: **Topic** • one • two")
    assert "\n\n### Example Structure" in out
    assert "\n- one\n- two" in out


def test_tidy_splits_a_very_long_paragraph_at_sentence_ends() -> None:
    sentences = ["This is sentence number %d and it has some words in it." % i for i in range(1, 9)]
    out = tidy_reply(" ".join(sentences))
    assert "\n\n" in out
    assert all(len(chunk) < 330 for chunk in out.split("\n\n"))


def test_tidy_leaves_short_text_and_code_blocks_untouched() -> None:
    code = "```python\nx = 1. 2. 3.  # not a list\n```"
    assert tidy_reply(code) == code
    assert tidy_reply("Short and sweet.") == "Short and sweet."


def test_tidy_never_changes_the_wording() -> None:
    text = (
        "Got it! Here's the plan: 1. Use headings. 2. Break content into points. "
        "3. Add emojis. ### Example **Day**: 1. Morning 2. Evening. " + "More words here. " * 30
    )
    assert "".join(tidy_reply(text).split()) == "".join(text.split())


def test_a_fresh_numbered_run_restarts_instead_of_continuing() -> None:
    result = render_markdown("1. a\n2. b\n3. c\n\n1. x\n2. y")
    assert result.count("<ol") == 2
    assert 'start="' not in result  # both lists count from 1


def test_tidy_puts_a_bold_label_after_a_sentence_on_its_own_line() -> None:
    out = tidy_reply("Keep it short and focused. **Example**: **Planning Your Day**: 1. a 2. b")
    assert "focused.\n\n**Example**" in out
