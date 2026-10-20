"""Aashi chat bubble component.

A single chat message rendered as a rounded shell. Two roles:

- :class:`ChatRole.USER` — the neutral ``user_bubble`` fill with primary text,
  aligned right. Compact and quiet; the accent is reserved for actions.
- :class:`ChatRole.ASSISTANT` — plain primary text directly on the canvas,
  aligned left, with no shell at all (UI-02C decision, ChatGPT style).

The user shell sharpens the corner nearest the sender (``radius.small``) while
the other three are ``radius.large``, which is how the eye reads which side a
bubble belongs to without drawing a tail. The assistant message has no shell
and therefore no corner treatment.

The bubble hugs its content: a short message produces a short bubble, and a long
one grows only up to its role's width cap — :data:`CHAT_BUBBLE_MAX_WIDTH_PX`
for the assistant, :data:`CHAT_BUBBLE_USER_MAX_WIDTH_PX` for the user — before
its label wraps. The label cap keeps prose ``_BUBBLE_PADDING`` inside the shell
cap on each side, so text wraps one step inside the shell and is never clipped.
It exposes :attr:`ChatBubble.alignment` so containers place it with
``layout.addWidget(bubble, 0, bubble.alignment)``.

The bubble re-styles itself whenever the owning :class:`ThemeManager` reports a
theme change.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from PySide6.QtWidgets import QSizePolicy

from math import ceil

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from aashi.ui.themes.definitions import Theme
from aashi.ui.themes.manager import ThemeManager
from aashi.ui.themes.qss import qss_variables
from aashi.ui.themes.qt_adapters import to_qfont
from aashi.ui.tokens.spacing import Space
from aashi.ui.tokens.typography import TextRole, style_for

__all__ = [
    "CHAT_BUBBLE_MAX_WIDTH_PX",
    "CHAT_BUBBLE_MIN_WIDTH_PX",
    "CHAT_BUBBLE_USER_MAX_WIDTH_PX",
    "ChatBubble",
    "ChatRole",
    "LABEL_MAX_WIDTH_PX",
]

CHAT_BUBBLE_MIN_WIDTH_PX: Final[int] = 60
"""Smallest bubble width, for a one- or two-word message."""

CHAT_BUBBLE_MAX_WIDTH_PX: Final[int] = 640
"""Widest assistant bubble; longer prose wraps inside the shell instead of
widening. Sits within the centred conversation column (``LAYOUT.content_reading``)
with internal gutters so the assistant reply reads at a generous measure
without touching the column edges."""

CHAT_BUBBLE_USER_MAX_WIDTH_PX: Final[int] = 520
"""Widest user bubble. User messages are compact by nature, so the cap sits
below the assistant's reading width but wider than before so long questions
wrap less in the wider conversation column."""

LABEL_MAX_WIDTH_PX: Final[int] = 616
"""Widest the assistant message label may be. Equals the assistant bubble cap
minus the two ``_BUBBLE_PADDING`` gutters (2 × 12 = 24 px), so text wraps one
step inside the shell and is never clipped by it. The user bubble computes its
own, tighter label cap from :data:`CHAT_BUBBLE_USER_MAX_WIDTH_PX` at runtime."""

_BUBBLE_PADDING: Final[int] = Space.SPACE_150.value
"""Uniform padding inside a bubble shell. UI-02C decision: 12 px replaces the
old 24 px card padding for a compact, modern rhythm."""


def _height_for_width(horizontal: QSizePolicy.Policy, vertical: QSizePolicy.Policy) -> QSizePolicy:
    """Build a size policy with the ``HeightForWidth`` flag set.

    ``QSizePolicy(horizontal, vertical)`` defaults the flag off, which makes
    parent layouts treat the widget as fixed-height (sizeHint) instead of
    asking how tall it needs to be at the width it is actually given. For
    word-wrapped chat text that under-sizes the shell and clips the last
    lines whenever the widget is narrower than its sizeHint width.
    """
    policy = QSizePolicy(horizontal, vertical)
    policy.setHeightForWidth(True)
    return policy


class _HuggingLabel(QLabel):
    """A word-wrapped label whose size hint is the text's natural width.

    A stock wrapped ``QLabel`` guesses a roughly square block, so long replies
    wrap far narrower than the column allows. This label measures the text's
    ideal single-run width instead and clamps it to its own maximum width, so
    short text hugs and long text fills the column before wrapping.
    """

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt override)
        doc = QTextDocument()
        doc.setDefaultFont(self.font())
        if self.textFormat() == Qt.TextFormat.PlainText:
            doc.setPlainText(self.text())
        else:
            doc.setHtml(self.text())
        width = min(ceil(doc.idealWidth()) + 2, self.maximumWidth())
        width = max(width, 1)
        return QSize(width, self.heightForWidth(width))


class ChatRole(StrEnum):
    """Which side of the conversation a bubble belongs to.

    Attributes:
        USER: The user's message — neutral fill, right-aligned.
        ASSISTANT: Aashi's message — plain text on the canvas, left-aligned.
    """

    USER = "user"
    ASSISTANT = "assistant"


class ChatBubble(QWidget):
    """A theme-aware chat message bubble.

    Args:
        theme_manager: The active theme manager; the bubble follows it for life.
        text: Initial message text.
        role: Which side of the conversation the bubble belongs to.
        parent: Optional Qt parent.
    """

    def __init__(
        self,
        theme_manager: ThemeManager,
        text: str = "",
        role: ChatRole = ChatRole.ASSISTANT,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._theme_manager = theme_manager
        self._role = role

        # A plain QWidget paints no background; QSS needs this to draw the fill.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # Maximum/Minimum is what makes the bubble hug its text: it can shrink
        # to fit short messages but never grows beyond its own size hint, so
        # the shell is as wide as the content (up to the role's width cap) and
        # the vertical dimension grows naturally with wrapped lines. No fixed
        # height anywhere — the layout derives it from the text.
        self.setMinimumWidth(CHAT_BUBBLE_MIN_WIDTH_PX)
        # HeightForWidth must be on the bubble's own size policy, not just the
        # widget's, or the parent layout never asks the bubble how tall it
        # needs to be at the width it is actually given. Without it the parent
        # takes the bubble's sizeHint height, which is only correct at the
        # sizeHint width — a narrower viewport would clip the wrapped text.
        self.setSizePolicy(_height_for_width(QSizePolicy.Maximum, QSizePolicy.Minimum))

        self._label = _HuggingLabel(text, self)
        self._label.setWordWrap(True)
        # Likewise the label must keep HeightForWidth on its size policy: the
        # bubble's internal layout only reports a valid totalHeightForWidth if
        # the label item advertises one, and setting a plain Preferred/Preferred
        # policy here silently clears that flag (a QLabel's default policy has
        # it set).
        self._label.setSizePolicy(_height_for_width(QSizePolicy.Preferred, QSizePolicy.Preferred))
        self._label.setTextFormat(Qt.TextFormat.RichText)
        # Chat text must be copyable; selection is the only sanctioned use of
        # the mouse on message text.
        self._label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        self._apply_width_caps()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            _BUBBLE_PADDING, _BUBBLE_PADDING, _BUBBLE_PADDING, _BUBBLE_PADDING
        )
        layout.addWidget(self._label)

        theme_manager.theme_changed.connect(self._restyle)
        self._restyle()

    @property
    def text(self) -> str:
        """The message text."""
        return self._label.text()

    def set_text(self, text: str) -> None:
        """Replace the message text."""
        self._label.setText(text)
        self._pin_height_to_width()

    @property
    def role(self) -> ChatRole:
        """Which side of the conversation this bubble belongs to."""
        return self._role

    def set_role(self, role: ChatRole) -> None:
        """Switch side and re-style in place."""
        if role is self._role:
            return
        self._role = role
        self._apply_width_caps()
        self._restyle()

    def _apply_width_caps(self) -> None:
        """Re-apply the bubble and label width caps for the current role.

        User bubbles cap narrower than assistant bubbles, and each label must
        wrap one step inside its own shell — the bubble cap minus the two
        ``_BUBBLE_PADDING`` gutters.
        """
        max_width = (
            CHAT_BUBBLE_USER_MAX_WIDTH_PX
            if self._role is ChatRole.USER
            else CHAT_BUBBLE_MAX_WIDTH_PX
        )
        self.setMaximumWidth(max_width)
        self._label.setMaximumWidth(max_width - 2 * _BUBBLE_PADDING)

    @property
    def alignment(self) -> Qt.AlignmentFlag:
        """The placement a container should give this bubble.

        Right for a user message, left for an assistant message. Pass it to
        ``layout.addWidget(bubble, 0, bubble.alignment)``.
        """
        if self._role is ChatRole.USER:
            return Qt.AlignmentFlag.AlignRight
        return Qt.AlignmentFlag.AlignLeft

    def resizeEvent(self, event) -> None:
        """Pin the shell to the height its text needs at its real width.

        A container wider than the bubble asks the bubble for the height at the
        *container's* width, not the width the bubble actually hugs to, so that
        height is too small for the narrower shell and the wrapped text clips.
        Reacting to the final geometry here and raising the bubble's minimum
        height to match its own width makes the parent layout re-measure it,
        which converges in one extra pass.
        """
        super().resizeEvent(event)
        self._pin_height_to_width()

    def _pin_height_to_width(self) -> None:
        """Raise the shell's minimum height to fit its label at its real width.

        The width is re-read on every pass so the pin tracks the bubble's final
        geometry: an early pass with a narrower shell reports a taller need,
        which the next layout pass (the shell is still width-hugging) corrects
        back down. The container always honours this minimum when it is larger
        than the height it derives from its own (wider) width, which is what
        stops the wrapped text from clipping. Invalidate the internal layout so
        the label is re-measured to the new height instead of keeping a stale,
        overflowed geometry from a narrower pass.
        """
        label_width = self._label.width()
        if label_width <= 0:
            return
        needed = self._label.heightForWidth(label_width) + 2 * _BUBBLE_PADDING
        if self.minimumHeight() != needed:
            self.setMinimumHeight(needed)
            self.layout().invalidate()
            self.updateGeometry()

    @property
    def word_wrap(self) -> bool:
        """Whether the message text wraps at the bubble's width."""
        return self._label.wordWrap()

    def _restyle(self, *_: object) -> None:
        """Regenerate the font and stylesheet from the active theme."""
        theme = self._theme_manager.theme
        self._label.setFont(to_qfont(style_for(TextRole.BODY)))
        self._pin_height_to_width()
        self.setStyleSheet(self._build_stylesheet(theme))

    def _build_stylesheet(self, theme: Theme) -> str:
        variables = qss_variables(theme)
        if self._role is ChatRole.USER:
            background = variables["color.surface.userBubble"]
            foreground = variables["color.text"]
            large = variables["radius.large"]
            small = variables["radius.small"]
            # Bottom-right is the corner nearest the sender on the right.
            corners = f"{large} {large} {small} {large}"
            radius = f"  border-radius: {corners};\n"
        else:
            # The assistant's message sits directly on the canvas with no shell
            # at all (UI-02C decision, ChatGPT style), so there is nothing to
            # round. The transparent border stays so high contrast can still
            # outline the message.
            background = "transparent"
            foreground = variables["color.text"]
            radius = ""

        stylesheet = (
            "ChatBubble QLabel {\n"
            "  background: transparent;\n"
            "  border: none;\n"
            "}\n"
            "ChatBubble {\n"
            f"  background-color: {background};\n"
            f"  color: {foreground};\n"
            f"  border: {variables['border.hairline']} solid transparent;\n"
            f"{radius}"
            "}\n"
        )
        if theme.high_contrast:
            # High contrast collapses every surface onto the canvas, so a solid
            # outline is what separates a bubble from the canvas around it.
            stylesheet += (
                "ChatBubble {\n"
                f"  border-color: {variables['color.border.strong']};\n"
                "}\n"
            )
        return stylesheet
