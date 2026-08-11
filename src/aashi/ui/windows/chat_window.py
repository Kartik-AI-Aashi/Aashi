"""Aashi chat window.

The main conversation surface: the :class:`AashiHeader` on top, a scrollable
stack of :class:`ChatBubble` messages in the middle and an :class:`AashiInput`
at the bottom. Messages are appended with :meth:`AashiChatWindow.add_message`,
which stacks them vertically (user right, assistant left, via each bubble's own
alignment) and scrolls the chat area to the newest message. Pressing Enter in
the input sends its text as a user message, which the OpenRouter client answers
on a worker thread so the UI stays responsive while the reply arrives. While a
reply is pending, a thinking bubble with a randomly chosen phrase stands in its
place and is swapped for the real answer when it arrives.

The window paints the ``color.canvas`` backdrop itself; every child component
applies its own tokens, so this module holds no visual values of its own.
"""

from __future__ import annotations

import random
import re

from PySide6.QtWidgets import QSizePolicy

from PySide6.QtCore import QObject, Qt, QThreadPool, QRunnable, QTimer, Signal
from PySide6.QtWidgets import QFileDialog, QFrame, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from aashi.ui.components.attachment_preview import AttachmentPreview
from aashi.ui.components.button import AashiButton, ButtonVariant
from aashi.ui.components.chat_bubble import ChatBubble, ChatRole
from aashi.ui.components.header import AashiHeader
from aashi.ui.components.input import AashiInput
from aashi.ui.services.document_input import (
    DocumentInputError,
    ScannedDocumentError,
    UnsupportedDocumentError,
    build_document_prompt,
    cap_document_text,
    extract_document,
    is_document_path,
)
from aashi.ui.services.image_input import (
    ImageInputError,
    encode_image_data_uri,
    is_image_path,
)
from aashi.ui.services.local_ai import _enforce_identity, fetch_response_hybrid
from aashi.ui.services.markdown_render import render_markdown
from aashi.ui.services.openrouter import fetch_vision_response
from aashi.ui.themes.definitions import Theme
from aashi.ui.themes.manager import ThemeManager
from aashi.ui.themes.qss import qss_variables
from aashi.ui.tokens.controls import ControlHeight
from aashi.ui.tokens.spacing import LAYOUT, SPACING, Space

__all__ = ["AashiChatWindow"]

# Fallback shown when an AI request fails. A user-facing string, not a design
# value, so it lives here as a module constant rather than as a token.
_ERROR_FALLBACK_MESSAGE: str = "Something went wrong"

# Shown when an attached image cannot be decoded for the vision model. Also
# user-facing copy, kept separate from the generic fallback so the user knows
# the attachment itself was the problem.
_IMAGE_READ_ERROR: str = "I couldn't read that image."

# Shown when an attached document cannot be read, is scanned, or is a format
# Aashi cannot extract. Kept distinct so the user knows the attachment itself
# was the problem, and so a scanned PDF is explained rather than silently
# reported as empty content.
_DOCUMENT_READ_ERROR: str = "I couldn't read that document."
_UNSUPPORTED_DOCUMENT_FORMAT: str = "I don't support that document format yet."
_SCANNED_PDF_MESSAGE: str = (
    "That PDF appears to contain scanned images, so I couldn't extract any text from it."
)
_EMPTY_DOCUMENT_MESSAGE: str = "I couldn't find any text in that document."

# Thinking phrases shown in the placeholder bubble while an AI reply is
# pending. Also user-facing copy, so they live here rather than as tokens.
# Each phrase is stored without its trailing ellipsis; the punctuation is
# chosen at render time so consecutive replies never read identically.
_THINKING_PHRASES: tuple[str, ...] = (
    "hmm, thinking",
    "wait a second",
    "let me think",
    "okay, one moment",
    "interesting question",
    "alright, thinking this through",
    "hmm, got it",
    "just a sec",
    "thinking",
    "hold on",
    "let me figure this out",
    "one moment",
)
_THINKING_PUNCTUATION: tuple[str, ...] = ("...", "…", "..", ".")


def _random_thinking_phrase() -> str:
    """Pick one thinking phrase and a subtle punctuation ending at random.

    The phrase and the ending are chosen independently, so the same phrase
    shown twice is unlikely to end the same way. Returns the full string to
    display in the thinking bubble.
    """
    return random.choice(_THINKING_PHRASES) + random.choice(_THINKING_PUNCTUATION)


# Typewriter reveal speed — how fast response text appears character by character.
_TYPEWRITER_INTERVAL_MS: int = 30
"""Milliseconds between typewriter ticks."""
_TYPEWRITER_CHARS_PER_TICK: int = 1
"""Characters revealed per tick (1 × ~33 ticks/s ≈ 30 chars/s)."""
# After revealing one of these characters the typewriter idles for an extra
# couple of ticks, so punctuation reads as a natural pause rather than a
# steady machine-like stream.
_TYPEWRITER_PAUSE_CHARS: str = ".!,:;?"
"""Characters that trigger a short typewriter pause."""
_TYPEWRITER_PAUSE_TICKS: int = 2
"""Extra ticks the typewriter idles after a pause character."""


def is_simple_message(msg: str) -> bool:
    """Return True for short, straightforward messages that need no thinking delay.

    Simple messages skip the thinking-indicator bubble entirely and jump straight
    to the typewriter reveal, so the user is never kept waiting for trivial
    questions.
    """
    return len(msg.strip()) < 15


# Replies are reformatted for display only — sentence-ending punctuation starts
# a new paragraph, numbered/bulleted list items begin on their own lines, and
# runs of blank lines collapse. The wording itself is never touched.
_SENTENCE_BREAK_RE = re.compile(r"(?<!\d)([.!?]) ")
_NUMBERED_ITEM_RE = re.compile(r"(?<!^)(\d+[.)]\s+)")
_BULLET_ITEM_RE = re.compile(r"^(\s*[-*+]\s+)", re.MULTILINE)


def _format_assistant_reply(text: str) -> str:
    """Reformat an assistant reply for readability without changing its meaning.

    Applies three whitespace-only transforms:

    1. A ``.`` / ``?`` / ``!`` followed by a space starts a new paragraph.
    2. Numbered (``1.``) and bulleted (``-`` / ``*``) items begin on their own
       lines — numbered markers are excluded from the sentence pass so ``1. item``
       is never split in half.
    3. Runs of 3+ newlines collapse to a single paragraph break.

    Returns the reformatted text.
    """
    # Numbered items first, so the sentence pass below cannot split "1. item".
    text = _NUMBERED_ITEM_RE.sub(r"\n\n\1", text)
    text = _SENTENCE_BREAK_RE.sub(r"\1\n\n", text)
    # Bulleted lines become their own paragraphs.
    text = _BULLET_ITEM_RE.sub(r"\n\n\1", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# Basic conversation memory: the last few turns (user + assistant) are replayed
# with each request so Aashi can refer back to recent context. Bounded, so
# memory never grows without limit.
_HISTORY_CONTEXT: int = 6
"""Number of recent turns sent with each request."""


class _AiWorker(QObject):
    """Signal bridge between the AI task and the chat window.

    Lives on the UI thread. A :class:`_AiTask` runs the blocking OpenRouter
    call on a pool thread and reports back by emitting :attr:`response_ready`
    or :attr:`failed`; because the bridge lives on the UI thread Qt delivers
    those emissions to the window as queued connections.
    """

    response_ready = Signal(str)
    failed = Signal()
    failed_with_message = Signal(str)


class _AiTask(QRunnable):
    """One OpenRouter request, run on a pool thread.

    The task holds the bridge and the message it must answer. Any failure —
    network, HTTP status, malformed body — degrades to the same fallback
    bubble, so the user never sees a traceback.
    """

    def __init__(self, bridge: _AiWorker, message: str) -> None:
        super().__init__()
        self._bridge = bridge
        self._message = message

    def run(self) -> None:
        try:
            reply = fetch_response_hybrid(self._message)
        except Exception:
            self._bridge.failed.emit()
        else:
            self._bridge.response_ready.emit(reply)


class _VisionAiTask(QRunnable):
    """One vision request, run on a pool thread.

    The image is read, resized and base64-encoded on the worker thread too, so
    a large attachment never blocks the UI. A decode failure surfaces a
    specific friendly message; an API failure degrades to the same generic
    fallback as a text request.
    """

    def __init__(self, bridge: _AiWorker, message: str, image_path: str) -> None:
        super().__init__()
        self._bridge = bridge
        self._message = message
        self._image_path = image_path

    def run(self) -> None:
        try:
            data_uri = encode_image_data_uri(self._image_path)
        except ImageInputError:
            self._bridge.failed_with_message.emit(_IMAGE_READ_ERROR)
            return
        try:
            reply = _enforce_identity(
                fetch_vision_response(self._message, data_uri)
            )
        except Exception:
            self._bridge.failed_with_message.emit(_ERROR_FALLBACK_MESSAGE)
        else:
            self._bridge.response_ready.emit(reply)


class _DocumentAiTask(QRunnable):
    """One document-understanding request, run on a pool thread.

    The attached document is extracted locally on the worker thread — a remote
    model can never reach the user's filesystem — and the extracted content is
    composed into a source-grounded prompt with the user's question before the
    request is sent. A document that cannot be read, is an unsupported format,
    or is a scanned PDF surfaces its own specific message rather than the
    generic fallback.
    """

    def __init__(self, bridge: _AiWorker, message: str, document_path: str) -> None:
        super().__init__()
        self._bridge = bridge
        self._message = message
        self._path = document_path

    def run(self) -> None:
        try:
            doc_text = extract_document(self._path)
        except UnsupportedDocumentError:
            self._bridge.failed_with_message.emit(_UNSUPPORTED_DOCUMENT_FORMAT)
            return
        except ScannedDocumentError:
            self._bridge.failed_with_message.emit(_SCANNED_PDF_MESSAGE)
            return
        except DocumentInputError:
            self._bridge.failed_with_message.emit(_DOCUMENT_READ_ERROR)
            return

        if not doc_text.strip():
            self._bridge.failed_with_message.emit(_EMPTY_DOCUMENT_MESSAGE)
            return

        from pathlib import Path

        capped, truncated = cap_document_text(doc_text)
        prompt = build_document_prompt(
            self._message, capped, Path(self._path).name, truncated=truncated
        )
        try:
            reply = fetch_response_hybrid(prompt)
        except Exception:
            self._bridge.failed.emit()
        else:
            self._bridge.response_ready.emit(reply)


class AashiChatWindow(QWidget):
    """A theme-aware chat conversation window.

    Args:
        theme_manager: The active theme manager; the window and every child
            component follow it for life.
        parent: Optional Qt parent.
    """

    def __init__(self, theme_manager: ThemeManager, parent=None) -> None:
        super().__init__(parent)
        self._theme_manager = theme_manager
        self._messages: list[ChatBubble] = []
        self._stick_to_bottom = False
        # The pending-reply placeholder bubble, or None when no reply is in
        # flight. Removed when the real answer arrives and typing begins.
        self._thinking_bubble: ChatBubble | None = None
        # Typewriter state — one bubble fills progressively via QTimer ticks.
        self._typewriter_bubble: ChatBubble | None = None
        self._typewriter_text: str = ""
        self._typewriter_index: int = 0
        self._typewriter_timer: QTimer | None = None
        self._typewriter_pause: int = 0
        # Bounded conversation memory — the last few turns are replayed with
        # each request so Aashi can refer back to what was just said.
        self._chat_history: list[dict[str, str]] = []
        # A single-threaded pool serializes AI requests so replies arrive in
        # the order the messages were sent, and runs them off the UI thread so
        # the network call never blocks the interface. The bridge lives on the
        # UI thread and carries the task's reply back as a queued signal.
        self._ai_worker = _AiWorker()
        self._ai_worker.response_ready.connect(self._append_ai_reply)
        self._ai_worker.failed.connect(self._append_error_reply)
        self._ai_worker.failed_with_message.connect(self._append_error_message)
        self._ai_pool = QThreadPool(self)
        self._ai_pool.setObjectName("aashi.aiThreadPool")
        self._ai_pool.setMaxThreadCount(1)

        # A plain QWidget paints no background; QSS needs this to draw the fill.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._header = AashiHeader(theme_manager)
        # Embedded: the composer pill below owns the chrome, so the input draws
        # no well of its own.
        self._input = AashiInput(theme_manager, embedded=True)
        self._input.returnPressed.connect(self._submit_message)
        self._input.setPlaceholderText("Message Aashi...")

        # File-attachment state and UI. ``_selected_file`` is the single source
        # of truth for the staged attachment; the preview chip only renders it.
        self._selected_file: str | None = None
        self._attachment_preview = AttachmentPreview(theme_manager)
        self._attachment_preview.setMaximumWidth(LAYOUT.content_reading)
        self._attachment_preview.removed.connect(self._remove_attachment)

        # Composer buttons — re-use existing theme-aware components so they
        # restyle automatically when the theme changes. Both are fixed 40×40
        # squares; the send button's radius is overridden to half its side so
        # it reads as a circle.
        self._attach_button = AashiButton("📎", theme_manager, ButtonVariant.GHOST)
        self._attach_button.setFixedSize(
            ControlHeight.DEFAULT.value, ControlHeight.DEFAULT.value
        )
        self._attach_button.clicked.connect(self._on_attach_clicked)

        self._send_button = AashiButton(
            "➤",
            theme_manager,
            ButtonVariant.PRIMARY,
            border_radius_px=ControlHeight.DEFAULT.value // 2,
        )
        self._send_button.setFixedSize(
            ControlHeight.DEFAULT.value, ControlHeight.DEFAULT.value
        )
        self._send_button.clicked.connect(self._submit_message)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.viewport().setAutoFillBackground(False)

        self._message_container = QWidget()
        self._message_layout = QVBoxLayout(self._message_container)
        self._message_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._message_layout.setContentsMargins(
            SPACING.card_padding,
            SPACING.card_padding,
            SPACING.card_padding,
            SPACING.card_padding,
        )
        self._message_layout.setSpacing(SPACING.chat_gap)
        self._message_layout.addStretch(1)
        self._scroll.setWidget(self._message_container)
        # Auto-scroll is driven by the scrollbar range, which only changes once
        # the scroll content has actually been resized.
        self._scroll.verticalScrollBar().rangeChanged.connect(
            self._on_chat_range_changed
        )

        layout = QVBoxLayout(self)
        # The bottom gutter lifts the composer off the window edge so it reads
        # as a floating input rather than a docked bar. No other margin is set
        # here: the header and message area provide their own insets.
        layout.setContentsMargins(0, 0, 0, SPACING.gutter_compact)
        layout.setSpacing(0)
        layout.addWidget(self._header)
        layout.addWidget(self._scroll, 1)
        # The staged-attachment chip sits above the composer, centred in the
        # same capped column as the pill so the two stay visually aligned.
        preview_row = QHBoxLayout()
        preview_row.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        preview_row.addWidget(self._attachment_preview)
        layout.addLayout(preview_row)

        # The composer is a rounded pill capped at the reading column and
        # centred inside a dedicated row, keeping a comfortable inset from the
        # screen edges on wide windows. The pill owns the chrome; the embedded
        # input inside it is transparent.  Attach button | input (stretch) |
        # send button.
        self._composer = QWidget()
        self._composer.setObjectName("aashiComposer")
        self._composer.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._composer.setMaximumWidth(LAYOUT.content_reading)

        pill = QHBoxLayout(self._composer)
        pill.setContentsMargins(
            Space.SPACE_100, Space.SPACE_050, Space.SPACE_100, Space.SPACE_050
        )
        pill.setSpacing(Space.SPACE_050)
        pill.addWidget(self._attach_button)
        pill.addWidget(self._input, 1)
        pill.addWidget(self._send_button)

        composer_row = QHBoxLayout()
        composer_row.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        composer_row.addWidget(self._composer)
        layout.addLayout(composer_row)

        theme_manager.theme_changed.connect(self._restyle)
        self._restyle()

    @property
    def header(self) -> AashiHeader:
        """The window's header."""
        return self._header

    @property
    def scroll_area(self) -> QScrollArea:
        """The scrollable chat area."""
        return self._scroll

    @property
    def input(self) -> AashiInput:
        """The message input at the bottom."""
        return self._input

    @property
    def message_count(self) -> int:
        """The number of messages added so far."""
        return len(self._messages)

    def add_message(self, text: str, is_user: bool) -> ChatBubble:
        """Append a message bubble and scroll it into view.

        Args:
            text: The message text.
            is_user: Whether this is the user's message (right-aligned) or
                Aashi's (left-aligned).

        Returns:
            The created bubble.
        """
        role = ChatRole.USER if is_user else ChatRole.ASSISTANT
        bubble = ChatBubble(self._theme_manager, text=text, role=role)
        # Insert just before the trailing stretch so messages always stack
        # from the top in insertion order. The alignment argument is the only
        # placement the container applies (right for the user, left for Aashi).
        # The bubble's own content-hugging size policy sizes it; the layout
        # pass derives width and height from the wrapped text.
        self._message_layout.insertWidget(
            self._message_layout.count() - 1,
            bubble, 0, bubble.alignment,
        )
        self._messages.append(bubble)
        # The layout resize is deferred, so the scroll happens when the
        # scrollbar range grows in the next layout pass — see
        # :meth:`_on_chat_range_changed`.
        self._stick_to_bottom = True
        bubble.updateGeometry()
        return bubble

    def _submit_message(self) -> None:
        """Send the input's text as a user message when Enter is pressed.

        Empty — or whitespace-only — input is ignored rather than sent. The
        user message appears immediately. For simple messages the thinking
        indicator is skipped; for complex ones a randomly-chosen phrase shows
        while the worker thread answers. The reply arrives via a typewriter
        that fills a single assistant bubble character by character.

        If a file is staged via the attach button, its content is appended to
        the message sent to the AI and its name is shown on a one-line
        attachment label (icon + filename) under the typed text in the user
        bubble. Images take the vision-capable route instead: the picture is
        sent to the vision model as real image data and never appears as file
        content in a text prompt. The staged attachment is cleared after use.
        """
        text = self._input.text().strip()
        if not text:
            return
        # Complete any in-progress typewriter so the previous reply is fully
        # visible before the new request starts.
        self._finish_typewriter()
        attachment = self._selected_file
        # The user bubble shows the typed text plus a one-line attachment label
        # (icon + filename, never the path). The message sent to the AI is built
        # separately below, so file content never appears in the chat.
        display_text = text
        if attachment is not None:
            from pathlib import Path

            icon = "🖼" if is_image_path(attachment) else "📎"
            display_text = text + f"\n{icon} {Path(attachment).name}"
        self.add_message(display_text, is_user=True)
        self._input.clear()

        if not is_simple_message(text):
            self._thinking_bubble = self.add_message(
                _random_thinking_phrase(), is_user=False
            )

        # An image routes to the vision-capable path: the picture is read,
        # resized and encoded on the worker thread and sent as a multimodal
        # request, while the conversation history keeps only the text so memory
        # stays bounded and replayable.
        if attachment is not None and is_image_path(attachment):
            self._chat_history.append({"role": "user", "content": text})
            self._request_vision_reply(self._build_history_prompt(), attachment)
            self._clear_attachment()
            return

        if attachment is not None and is_document_path(attachment):
            # PDF / Word: extract the document locally on the worker thread and
            # ask the AI with the extracted content — a remote model can never
            # read the filesystem. The extracted content is not stored in the
            # conversation history, so it is never replayed on later turns.
            self._chat_history.append({"role": "user", "content": text})
            self._request_document_reply(self._build_history_prompt(), attachment)
            self._clear_attachment()
            return

        # Build the message to send to the AI — file content is appended here
        # but never shown in the user bubble.
        ai_message = text
        if attachment is not None:
            ai_message += (
                "\n\n[Attached File Content]:\n" + self._read_file_content()
            )
            self._clear_attachment()
        # Basic conversation memory: remember this turn and ask the AI with the
        # recent transcript instead of the bare message, so it can refer back.
        self._chat_history.append({"role": "user", "content": ai_message})
        self._request_reply(self._build_history_prompt())

    def _request_reply(self, message: str) -> None:
        """Ask the AI pool to answer ``message`` off the UI thread."""
        self._ai_pool.start(_AiTask(self._ai_worker, message))

    def _request_vision_reply(self, message: str, image_path: str) -> None:
        """Ask the AI pool to answer ``message`` with ``image_path`` attached.

        The image is read and encoded inside the worker task so the UI never
        blocks on a large attachment. Runs on the same single-threaded pool as
        text requests, so replies stay ordered.
        """
        self._ai_pool.start(_VisionAiTask(self._ai_worker, message, image_path))

    def _request_document_reply(self, message: str, document_path: str) -> None:
        """Ask the AI pool to extract ``document_path`` and answer ``message``.

        The document is read and extracted inside the worker task so a large
        PDF/DOCX never blocks the UI. Runs on the same single-threaded pool as
        text and vision requests, so replies stay ordered.
        """
        self._ai_pool.start(
            _DocumentAiTask(self._ai_worker, message, document_path)
        )

    def _build_history_prompt(self) -> str:
        """Flatten the recent conversation into one string for the AI worker.

        ``fetch_response_hybrid`` accepts a single message string, so the last
        ``_HISTORY_CONTEXT`` turns (user + assistant) are joined into a
        transcript with the newest message last. Older turns are dropped —
        memory stays bounded.
        """
        turns = self._chat_history[-_HISTORY_CONTEXT:]
        lines = [
            f"{'User' if turn['role'] == 'user' else 'Assistant'}: {turn['content']}"
            for turn in turns
        ]
        return "\n\n".join(lines)

    def _append_ai_reply(self, reply: str) -> None:
        """Show the assistant's reply with a typewriter effect. Runs on the UI thread.

        Any pending thinking bubble is removed first. The reply is remembered in
        the conversation history (unformatted) and then reformatted for reading
        before ONE empty assistant bubble is created and a QTimer fills it
        character by character, so the response looks like it is being typed in
        real time.
        """
        self._remove_thinking_bubble()
        self._chat_history.append({"role": "assistant", "content": reply})
        formatted = _format_assistant_reply(reply)
        self._start_typewriter(render_markdown(formatted))

    def _append_error_reply(self) -> None:
        """Show the fallback bubble when an AI request fails."""
        self._append_error_message(_ERROR_FALLBACK_MESSAGE)

    def _append_error_message(self, message: str) -> None:
        """Show ``message`` as an assistant bubble, replacing the thinking bubble.

        Used for any user-facing failure (network, API, or an unreadable
        attachment) so the user sees a normal message rather than a traceback.
        """
        self._remove_thinking_bubble()
        self.add_message(message, is_user=False)

    # -- typewriter -----------------------------------------------------------

    def _remove_thinking_bubble(self) -> None:
        """Detach and destroy the pending thinking placeholder, if any."""
        if self._thinking_bubble is None:
            return
        bubble = self._thinking_bubble
        self._thinking_bubble = None
        self._message_layout.removeWidget(bubble)
        if bubble in self._messages:
            self._messages.remove(bubble)
        bubble.deleteLater()

    def _finish_typewriter(self) -> None:
        """Show the full text of any in-progress typewriter immediately."""
        if self._typewriter_timer is None or self._typewriter_bubble is None:
            return
        self._typewriter_timer.stop()
        self._typewriter_bubble.set_text(self._typewriter_text)
        self._typewriter_bubble = None
        self._typewriter_text = ""
        self._typewriter_index = 0
        self._typewriter_pause = 0
        self._typewriter_timer = None

    def _start_typewriter(self, text: str) -> None:
        """Begin a character-by-character reveal in a new assistant bubble."""
        self._finish_typewriter()
        self._typewriter_bubble = self.add_message("", is_user=False)
        self._typewriter_text = text
        self._typewriter_index = 0
        self._typewriter_pause = 0
        timer = QTimer(self)
        timer.setInterval(_TYPEWRITER_INTERVAL_MS)
        timer.timeout.connect(self._typewriter_tick)
        self._typewriter_timer = timer
        timer.start()

    def _typewriter_tick(self) -> None:
        """Advance the typewriter by one step and scroll to keep it in view."""
        if self._typewriter_pause > 0:
            # Extra idle ticks after punctuation make the reveal read naturally.
            self._typewriter_pause -= 1
            return
        end = min(
            self._typewriter_index + _TYPEWRITER_CHARS_PER_TICK,
            len(self._typewriter_text),
        )
        self._typewriter_index = end
        self._typewriter_bubble.set_text(self._typewriter_text[:end])
        self._stick_to_bottom = True
        if end >= len(self._typewriter_text):
            self._typewriter_timer.stop()
            self._typewriter_bubble = None
            self._typewriter_timer = None
            return
        # A short beat after punctuation so the reveal never reads machine-like.
        if self._typewriter_text[end - 1] in _TYPEWRITER_PAUSE_CHARS:
            self._typewriter_pause = _TYPEWRITER_PAUSE_TICKS

    def _on_attach_clicked(self) -> None:
        """Open a file picker and stage the selected file for sending."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Attach file",
            "",
            (
                "All supported (*.txt *.pdf *.docx *.png *.jpg *.jpeg *.webp *.gif *.bmp);;"
                "Text files (*.txt);;"
                "PDF files (*.pdf);;"
                "Word documents (*.docx);;"
                "Images (*.png *.jpg *.jpeg *.webp *.gif *.bmp);;"
                "All files (*)"
            ),
        )
        if path:
            self._selected_file = path
            self._attachment_preview.set_attachment(path)

    def _read_file_content(self) -> str:
        """Read the attached document and return its content for the AI prompt.

        Text files are read as UTF-8; PDFs are extracted via ``pypdf``. Images
        are not handled here — they take the vision-capable path
        (:meth:`_submit_message`) and are sent as real image data instead. On
        any read error a fallback string is returned so the conversation flow
        is never broken.
        """
        from pathlib import Path

        path = Path(self._selected_file)
        suffix = path.suffix.lower()

        # PDF — extract text via pypdf.
        if suffix == ".pdf":
            try:
                from pypdf import PdfReader

                reader = PdfReader(str(path))
                pages = [page.extract_text() or "" for page in reader.pages]
                return "\n".join(pages).strip()
            except Exception:
                return "[Unable to read file content]"

        # Text files and anything else — try UTF-8.
        try:
            return path.read_text(encoding="utf-8")
        except Exception:
            return "[Unable to read file content]"

    def _clear_attachment(self) -> None:
        """Drop the staged attachment and hide its preview."""
        self._selected_file = None
        self._attachment_preview.clear()

    def _remove_attachment(self) -> None:
        """Handle the preview's remove button.

        Clears the staged attachment and the preview, leaving whatever text the
        user has typed untouched.
        """
        self._clear_attachment()

    def _on_chat_range_changed(self, _minimum: int, maximum: int) -> None:
        """Keep the newest message in view after an append.

        Fires only once the scroll content has been resized, so ``maximum`` is
        correct here — unlike a zero-timer, which can fire before the layout
        pass that follows a batch of inserts. The flag limits the scroll to
        appends rather than every unrelated range change, such as a resize.
        """
        if self._stick_to_bottom:
            self._stick_to_bottom = False
            scrollbar = self._scroll.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def _restyle(self, *_: object) -> None:
        """Regenerate the window's backdrop and composer chrome."""
        theme = self._theme_manager.theme
        self.setStyleSheet(self._build_stylesheet(theme))
        self._composer.setStyleSheet(self._build_composer_stylesheet(theme))

    def _build_stylesheet(self, theme: Theme) -> str:
        variables = qss_variables(theme)
        return (
            "AashiChatWindow {\n"
            f"  background-color: {variables['color.canvas']};\n"
            "}\n"
        )

    def _build_composer_stylesheet(self, theme: Theme) -> str:
        """Style the composer pill: an elevated surface with a hairline edge."""
        variables = qss_variables(theme)
        stylesheet = (
            "QWidget#aashiComposer {\n"
            f"  background-color: {variables['color.surface.elevated']};\n"
            f"  border: {variables['border.hairline']} solid "
            f"{variables['color.border']};\n"
            f"  border-radius: {variables['radius.large']};\n"
            "}\n"
        )
        if theme.high_contrast:
            # High contrast collapses the elevated surface onto the canvas, so
            # a solid outline is what separates the pill from the window.
            stylesheet += (
                "QWidget#aashiComposer {\n"
                f"  border-color: {variables['color.border.strong']};\n"
                "}\n"
            )
        return stylesheet
