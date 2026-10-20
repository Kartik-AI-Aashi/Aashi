"""Verify the UI-02B chat bubble component.

Creation, the two roles, alignment, token-driven fills, the asymmetric corner
treatment, token padding, content-hugging sizing with word wrap, and re-styling
when the theme changes.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pytestqt", reason="pytest-qt is required for GUI tests")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QVBoxLayout, QWidget  # noqa: E402

from aashi.ui.components.chat_bubble import (  # noqa: E402
    CHAT_BUBBLE_MAX_WIDTH_PX,
    CHAT_BUBBLE_MIN_WIDTH_PX,
    LABEL_MAX_WIDTH_PX,
    ChatBubble,
    ChatRole,
)
from aashi.ui.themes.definitions import DARK_THEME, LIGHT_THEME  # noqa: E402
from aashi.ui.themes.manager import ThemeManager  # noqa: E402
from aashi.ui.themes.mode import ColorScheme, ThemeMode  # noqa: E402
from aashi.ui.themes.qss import qss_variables  # noqa: E402
from aashi.ui.themes.system import SystemPreferences  # noqa: E402
from aashi.ui.tokens.spacing import Space  # noqa: E402


def _manager() -> ThemeManager:
    return ThemeManager(system_reader=lambda: SystemPreferences(
        color_scheme=ColorScheme.DARK,
        high_contrast=False,
        reduced_motion=False,
    ))


@pytest.mark.parametrize("role", list(ChatRole))
def test_bubble_builds_for_every_role(qtbot, role: ChatRole) -> None:
    bubble = ChatBubble(_manager(), "Hello", role=role)
    qtbot.addWidget(bubble)

    assert bubble.role is role
    assert bubble.text == "Hello"
    assert bubble.styleSheet()


def test_user_aligns_right_and_assistant_aligns_left(qtbot) -> None:
    user = ChatBubble(_manager(), "hi", role=ChatRole.USER)
    qtbot.addWidget(user)
    assert user.alignment == Qt.AlignmentFlag.AlignRight

    assistant = ChatBubble(_manager(), "hi", role=ChatRole.ASSISTANT)
    qtbot.addWidget(assistant)
    assert assistant.alignment == Qt.AlignmentFlag.AlignLeft


def test_user_uses_the_neutral_bubble_and_assistant_has_no_shell(qtbot) -> None:
    user = ChatBubble(_manager(), "hi", role=ChatRole.USER)
    qtbot.addWidget(user)
    assert DARK_THEME.palette.surface.user_bubble.css in user.styleSheet()
    assert DARK_THEME.palette.text.primary.css in user.styleSheet()

    assistant = ChatBubble(_manager(), "hi", role=ChatRole.ASSISTANT)
    qtbot.addWidget(assistant)
    assert "background-color: transparent" in assistant.styleSheet()
    assert DARK_THEME.palette.text.primary.css in assistant.styleSheet()


def test_corner_radius_points_at_the_sender(qtbot) -> None:
    variables = qss_variables(DARK_THEME)
    large = variables["radius.large"]
    small = variables["radius.small"]

    user = ChatBubble(_manager(), "hi", role=ChatRole.USER)
    qtbot.addWidget(user)
    assert f"border-radius: {large} {large} {small} {large};" in user.styleSheet()

    # The assistant message has no shell, so there is no corner to round.
    assistant = ChatBubble(_manager(), "hi", role=ChatRole.ASSISTANT)
    qtbot.addWidget(assistant)
    assert "background-color: transparent" in assistant.styleSheet()
    assert "border-radius:" not in assistant.styleSheet()


def test_padding_comes_from_the_bubble_padding_token(qtbot) -> None:
    bubble = ChatBubble(_manager(), "hi")
    qtbot.addWidget(bubble)

    margins = bubble.layout().contentsMargins()
    assert margins.left() == Space.SPACE_150.value
    assert margins.top() == Space.SPACE_150.value


def test_text_wraps_and_is_capped_at_the_bubble_maximum(qtbot) -> None:
    bubble = ChatBubble(_manager(), "word " * 200)
    qtbot.addWidget(bubble)

    assert bubble.word_wrap
    assert bubble.minimumWidth() == CHAT_BUBBLE_MIN_WIDTH_PX
    assert bubble.maximumWidth() == CHAT_BUBBLE_MAX_WIDTH_PX


def test_label_wraps_before_the_bubble_shell(qtbot) -> None:
    bubble = ChatBubble(_manager(), "word " * 200)
    qtbot.addWidget(bubble)

    label = bubble.layout().itemAt(0).widget()
    assert label.wordWrap()
    assert label.maximumWidth() == LABEL_MAX_WIDTH_PX


def test_short_message_hugs_its_content(qtbot) -> None:
    host = QWidget()
    layout = QVBoxLayout(host)
    bubble = ChatBubble(_manager(), "hi", role=ChatRole.USER)
    layout.addWidget(bubble, 0, bubble.alignment)
    qtbot.addWidget(host)
    host.resize(800, 300)
    host.show()

    qtbot.wait(10)

    # Given plenty of room, a one-word message still stays narrow instead of
    # spanning the host — the Maximum horizontal policy hugs the text.
    assert bubble.width() < 200


def test_long_message_wraps_inside_the_cap(qtbot) -> None:
    host = QWidget()
    layout = QVBoxLayout(host)
    # Long enough that the label's natural wrap width exceeds the (larger)
    # bubble cap in the offscreen font metrics, so it truly clamps to the cap
    # rather than sitting at a narrower natural width.
    bubble = ChatBubble(_manager(), "word " * 2000, role=ChatRole.ASSISTANT)
    layout.addWidget(bubble, 0, bubble.alignment)
    qtbot.addWidget(host)
    host.resize(800, 300)
    host.show()

    qtbot.wait(10)

    # Long prose is clamped to the bubble maximum and grows in height (wraps)
    # rather than overflowing or being clipped.
    assert bubble.width() == CHAT_BUBBLE_MAX_WIDTH_PX
    assert bubble.height() > 120


def test_set_text_and_set_role_update_in_place(qtbot) -> None:
    bubble = ChatBubble(_manager(), "before", role=ChatRole.ASSISTANT)
    qtbot.addWidget(bubble)

    bubble.set_text("after")
    assert bubble.text == "after"

    bubble.set_role(ChatRole.USER)
    assert bubble.role is ChatRole.USER
    assert DARK_THEME.palette.surface.user_bubble.css in bubble.styleSheet()


def test_bubble_restyles_when_the_theme_changes(qtbot) -> None:
    manager = _manager()
    bubble = ChatBubble(manager, "hi", role=ChatRole.USER)
    qtbot.addWidget(bubble)
    assert DARK_THEME.palette.surface.user_bubble.css in bubble.styleSheet()

    manager.set_mode(ThemeMode.LIGHT)

    assert LIGHT_THEME.palette.surface.user_bubble.css in bubble.styleSheet()


def test_high_contrast_adds_a_permanent_outline(qtbot) -> None:
    manager = ThemeManager(system_reader=lambda: SystemPreferences(
        color_scheme=ColorScheme.DARK,
        high_contrast=True,
        reduced_motion=False,
    ))
    bubble = ChatBubble(manager, "hi", role=ChatRole.USER)
    qtbot.addWidget(bubble)

    assert manager.theme.high_contrast
    assert manager.theme.palette.border.strong.css in bubble.styleSheet()
