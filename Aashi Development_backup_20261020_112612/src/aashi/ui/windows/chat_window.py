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
import logging
import os
import tempfile
from pathlib import Path

from PySide6.QtWidgets import QSizePolicy

from PySide6.QtCore import QEvent, QObject, Qt, QThreadPool, QRunnable, QTimer, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from aashi.ui.components.attachment_preview import AttachmentPreview
from aashi.ui.components.button import AashiButton, ButtonVariant
from aashi.ui.components.chat_bubble import ChatBubble, ChatRole
from aashi.ui.components.header import AashiHeader
from aashi.ui.components.input import AashiInput
from aashi.ui.components.navigation import NavigationSidebar, SidebarMode
from aashi.automation import (
    AssistantRuntime,
    ActionStatus,
    MemoryStore,
    MonitoringObservation,
    RequestOutcome,
    SpeechEvent,
    SpeechOperation,
    SpeechState,
    TaskState,
)
from aashi.constants import ENV_VAR_PROACTIVE_ENABLED
from aashi.config.assistant_settings import AutomationSettings
from aashi.emotion import EmotionLayer, Prepared
from aashi.ui.services.document_input import (
    DocumentInputError,
    ScannedDocumentError,
    UnsupportedDocumentError,
    build_document_prompt,
    cap_document_text,
    extract_document,
    is_document_path,
    render_pdf_pages_as_images,
)
from aashi.ui.services.image_input import (
    ImageInputError,
    encode_image_data_uri,
    is_image_path,
)
from aashi.ui.services.local_ai import (
    _enforce_identity,
    fetch_response_hybrid,
    format_provider_error,
)
from aashi.ui.services.markdown_render import render_markdown, tidy_reply
from aashi.ui.services import titles as titles_service
from aashi.ui.services.openrouter import fetch_vision_response
from aashi.paths import resolve_paths
from aashi.storage import ConversationRepository, get_database
from aashi.ui.themes.definitions import Theme
from aashi.ui.themes.manager import ThemeManager
from aashi.ui.themes.qss import qss_variables
from aashi.ui.tokens.controls import ControlHeight
from aashi.ui.tokens.spacing import LAYOUT, SPACING, Space
from aashi.ui.windows.settings_dialog import AssistantSettingsDialog

__all__ = ["AashiChatWindow"]

_logger = logging.getLogger(__name__)

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

_TYPEWRITER_MAX_TICKS: int = 220
"""Upper bound on reveal ticks, so long replies finish in a few seconds."""
"""Extra ticks the typewriter idles after a pause character."""


def is_simple_message(msg: str) -> bool:
    """Return True for short, straightforward messages that need no thinking delay.

    Simple messages skip the thinking-indicator bubble entirely and jump straight
    to the typewriter reveal, so the user is never kept waiting for trivial
    questions.
    """
    return len(msg.strip()) < 15


# Replies are shown through ``tidy_reply`` (repairs walls of text) and
# ``render_markdown`` (headings, lists, bold, code …); see
# ``aashi.ui.services.markdown_render``. The wording itself is never touched.


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
    title_ready = Signal(int, str)
    automation_ready = Signal(object)
    task_status = Signal(str)
    speech_ready = Signal(object)
    monitor_ready = Signal(object)
    monitor_failed = Signal(str)


class _AiTask(QRunnable):
    """One OpenRouter request, run on a pool thread.

    The task holds the bridge and the message it must answer. Network, HTTP,
    and response failures are logged with their traceback and converted to a
    bounded provider diagnostic for the chat bubble; raw exceptions never cross
    into the UI.
    """

    def __init__(self, bridge: _AiWorker, message: str) -> None:
        super().__init__()
        self._bridge = bridge
        self._message = message

    def run(self) -> None:
        try:
            reply = fetch_response_hybrid(self._message)
        except Exception as exc:
            # Keep the full exception chain in the local log for diagnosis, but
            # only send the bounded provider explanation to the chat bubble.
            _logger.exception("Text-generation request failed")
            self._bridge.failed_with_message.emit(format_provider_error(exc))
        else:
            self._bridge.response_ready.emit(reply)


class _TitleTask(QRunnable):
    """Ask the AI for a short title for a conversation's first question.

    Runs on its own pool so it never delays the real answer. Any failure just
    means the instant heuristic title stays.
    """

    def __init__(self, bridge: _AiWorker, conversation_id: int, question: str) -> None:
        super().__init__()
        self._bridge = bridge
        self._conversation_id = conversation_id
        self._question = question

    def run(self) -> None:
        title = titles_service.fetch_ai_title(self._question)
        if title:
            self._bridge.title_ready.emit(self._conversation_id, title)


class _VisionAiTask(QRunnable):
    """One vision request, run on a pool thread.

    The image(s) are read, resized and base64-encoded on the worker thread too,
    so large attachments never block the UI. A decode failure surfaces a
    specific friendly message; an API failure degrades to the same generic
    fallback as a text request.
    """

    def __init__(
        self,
        bridge: _AiWorker,
        message: str,
        image_paths: str | list[str],
    ) -> None:
        super().__init__()
        self._bridge = bridge
        self._message = message
        self._image_paths = image_paths

    def run(self) -> None:
        paths = [self._image_paths] if isinstance(self._image_paths, str) else self._image_paths
        data_uris = []
        for path in paths:
            try:
                data_uri = encode_image_data_uri(path)
                data_uris.append(data_uri)
            except ImageInputError:
                self._bridge.failed_with_message.emit(_IMAGE_READ_ERROR)
                return
        try:
            reply = _enforce_identity(
                fetch_vision_response(self._message, data_uris)
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
    request is sent. A document that cannot be read or is an unsupported format
    surfaces its own specific message. A scanned PDF is rendered as images and
    routed through the vision pipeline so the user gets an answer.
    """

    def __init__(self, bridge: _AiWorker, message: str, document_path: str) -> None:
        super().__init__()
        self._bridge = bridge
        self._message = message
        self._path = document_path

    def run(self) -> None:
        # First, try normal text extraction
        try:
            doc_text = extract_document(self._path)
        except UnsupportedDocumentError:
            self._bridge.failed_with_message.emit(_UNSUPPORTED_DOCUMENT_FORMAT)
            return
        except ScannedDocumentError:
            # Scanned PDF — render pages as images and route through vision
            self._handle_scanned_pdf()
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


    def _handle_scanned_pdf(self) -> None:
        """Render scanned PDF pages as images and send through vision pipeline."""
        try:
            # Import here to avoid hard dependency at module load time
            from aashi.ui.services.document_input import render_pdf_pages_as_images
        except ImportError:
            self._bridge.failed_with_message.emit(
                "Scanned PDF support requires PyMuPDF (pip install pymupdf)."
            )
            return

        try:
            image_paths = render_pdf_pages_as_images(self._path, max_pages=10)
        except DocumentInputError as exc:
            self._bridge.failed_with_message.emit(f"Could not render PDF pages: {exc}")
            return

        if not image_paths:
            self._bridge.failed_with_message.emit(_EMPTY_DOCUMENT_MESSAGE)
            return

        # Build a prompt asking the vision model about the scanned document
        from pathlib import Path

        filename = Path(self._path).name
        prompt = (
            f'USER QUESTION:\n{self._message}\n\n'
            f'ATTACHED DOCUMENT (scanned PDF rendered as images): "{filename}"\n'
            f'The document has {len(image_paths)} page(s) shown as images below.\n\n'
            f'Answer the user\'s question using ONLY the content visible in these images. '
            f'Do not invent or guess information that is not in the document. '
            f'If the document does not contain the information, say that it '
            f'could not be found in the document.'
        )

        try:
            reply = _enforce_identity(fetch_vision_response(prompt, image_paths))
        except Exception:
            self._bridge.failed_with_message.emit(_ERROR_FALLBACK_MESSAGE)
        else:
            self._bridge.response_ready.emit(reply)


class _AutomationTask(QRunnable):
    """Run one structured desktop request away from the Qt UI thread."""

    def __init__(
        self,
        bridge: _AiWorker,
        runtime: AssistantRuntime,
        message: str,
        *,
        speaker_verified: bool = True,
    ) -> None:
        super().__init__()
        self._bridge = bridge
        self._runtime = runtime
        self._message = message
        self._speaker_verified = speaker_verified

    def run(self) -> None:
        outcome = self._runtime.execute_request(
            self._message,
            status_callback=self._bridge.task_status.emit,
            speaker_verified=self._speaker_verified,
        )
        self._bridge.automation_ready.emit(outcome)


class _SpeechTask(QRunnable):
    """Perform one recognition or synthesis call without blocking Qt."""

    def __init__(self, bridge: _AiWorker, runtime: AssistantRuntime, *, text: str | None = None) -> None:
        super().__init__()
        self._bridge = bridge
        self._runtime = runtime
        self._text = text

    def run(self) -> None:
        event = self._runtime.speech.listen() if self._text is None else self._runtime.speech.speak(self._text)
        self._bridge.speech_ready.emit(event)


class _MonitorTask(QRunnable):
    """Poll the optional screen monitor without blocking the Qt UI thread."""

    def __init__(self, bridge: _AiWorker, runtime: AssistantRuntime) -> None:
        super().__init__()
        self._bridge = bridge
        self._runtime = runtime

    def run(self) -> None:
        try:
            observation = self._runtime.poll_monitor()
        except Exception as exc:
            _logger.exception("Screen-monitor poll failed")
            self._bridge.monitor_failed.emit(str(exc))
        else:
            self._bridge.monitor_ready.emit(observation)


class AashiChatWindow(QWidget):
    """A theme-aware chat conversation window.

    Args:
        theme_manager: The active theme manager; the window and every child
            component follow it for life.
        parent: Optional Qt parent.
    """

    talking_mode_changed = Signal(bool)
    talking_status_changed = Signal(str)
    screen_monitoring_changed = Signal(bool)
    screen_monitoring_status_changed = Signal(str)
    task_status_changed = Signal(str)

    def __init__(
        self,
        theme_manager: ThemeManager,
        parent=None,
        *,
        runtime: AssistantRuntime | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme_manager = theme_manager
        self._messages: list[ChatBubble] = []
        self._stick_to_bottom = False
        self._refreshing_sidebar = False  # Re-entrancy guard
        # The pending-reply placeholder bubble, or None when no reply is in
        # flight. Removed when the real answer arrives and typing begins.
        self._thinking_bubble: ChatBubble | None = None
        # Typewriter state — one bubble fills progressively via QTimer ticks.
        self._typewriter_bubble: ChatBubble | None = None
        self._typewriter_text: str = ""
        self._typewriter_step: int = _TYPEWRITER_CHARS_PER_TICK
        self._typewriter_index: int = 0
        self._typewriter_timer: QTimer | None = None
        self._typewriter_pause: int = 0
        # Bounded conversation memory — the last few turns are replayed with
        # each request so Aashi can refer back to what was just said.
        self._chat_history: list[dict[str, str]] = []
        # Emotion / personality layer (see aashi.emotion): presentation only.
        self._emotion = EmotionLayer()
        self._pending_emotion: Prepared | None = None
        self._talking_mode = False
        self._speech_output_verified = False
        self._speech_output_failed = False
        self._screen_monitoring = False
        self._task_status = TaskState.IDLE.value
        self._runtime = runtime or AssistantRuntime.from_environment()
        self._chat_status = TaskState.IDLE.value
        self._desktop_status = TaskState.IDLE.value
        self._voice_status = "Ready" if self._runtime.speech.available else "Unavailable"
        self._monitor_status = "Ready" if self._runtime.monitor is not None else "Unavailable"
        self._monitor_poll_in_flight = False
        self._memory = MemoryStore(resolve_paths().user_data_dir / "memory.json")
        self._monitor_timer = QTimer(self)
        self._monitor_timer.timeout.connect(self._poll_screen_monitor)
        # The callback is invoked only by an explicit screen-inspection action.
        # It is intentionally not connected to a timer or hidden background loop.
        self._runtime.vision_analyzer = self._analyze_screen_capture
        # Conversation persistence — backed by the application-owned SQLite
        # database. None until a conversation is created or loaded.
        self._repository: ConversationRepository | None = None
        self._conversation_id: int | None = None
        # A single-threaded pool serializes AI requests so replies arrive in
        # the order the messages were sent, and runs them off the UI thread so
        # the network call never blocks the interface. The bridge lives on the
        # UI thread and carries the task's reply back as a queued signal.
        self._ai_worker = _AiWorker()
        self._ai_worker.response_ready.connect(self._append_ai_reply)
        self._ai_worker.failed.connect(self._append_error_reply)
        self._ai_worker.failed_with_message.connect(self._append_error_message)
        self._ai_worker.title_ready.connect(self._apply_ai_title)
        self._ai_worker.automation_ready.connect(self._append_automation_reply)
        self._ai_worker.task_status.connect(self._set_desktop_status)
        self._ai_worker.speech_ready.connect(self._handle_speech_event)
        self._ai_worker.monitor_ready.connect(self._handle_monitor_observation)
        self._ai_worker.monitor_failed.connect(self._handle_monitor_failure)
        self._title_pool = QThreadPool(self)
        self._title_pool.setObjectName("aashi.titleThreadPool")
        self._title_pool.setMaxThreadCount(1)
        self._ai_pool = QThreadPool(self)
        self._ai_pool.setObjectName("aashi.aiThreadPool")
        self._ai_pool.setMaxThreadCount(1)
        self._speech_pool = QThreadPool(self)
        self._speech_pool.setObjectName("aashi.speechThreadPool")
        self._speech_pool.setMaxThreadCount(1)
        self._monitor_pool = QThreadPool(self)
        self._monitor_pool.setObjectName("aashi.monitorThreadPool")
        self._monitor_pool.setMaxThreadCount(1)

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
        self._attach_button = AashiButton(
            "📎",
            theme_manager,
            ButtonVariant.GHOST,
            border_radius_px=ControlHeight.DEFAULT.value // 2,
        )
        self._attach_button.setFixedSize(
            ControlHeight.DEFAULT.value, ControlHeight.DEFAULT.value
        )
        self._attach_button.setAccessibleName("Attach file")
        self._attach_button.setToolTip("Attach an image, PDF, DOCX, or text file")
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
        self._send_button.setAccessibleName("Send message")
        self._send_button.setToolTip("Send message")
        self._send_button.clicked.connect(self._submit_message)

        self._mic_button = AashiButton(
            "🎙",
            theme_manager,
            ButtonVariant.GHOST,
            border_radius_px=ControlHeight.DEFAULT.value // 2,
        )
        self._mic_button.setFixedSize(ControlHeight.DEFAULT.value, ControlHeight.DEFAULT.value)
        self._mic_button.setAccessibleName("Listen through microphone")
        self._mic_button.setToolTip("Listen once (optional microphone adapter)")
        self._mic_button.clicked.connect(self._listen_once)

        self._screen_button = AashiButton(
            "🖥",
            theme_manager,
            ButtonVariant.GHOST,
            border_radius_px=ControlHeight.DEFAULT.value // 2,
        )
        self._screen_button.setFixedSize(ControlHeight.DEFAULT.value, ControlHeight.DEFAULT.value)
        self._screen_button.setAccessibleName("Inspect screen")
        self._screen_button.setToolTip("Inspect the current screen on demand")
        self._screen_button.clicked.connect(lambda: self._request_supported_action("Look at my screen"))

        self._monitor_button = AashiButton(
            "👁",
            theme_manager,
            ButtonVariant.GHOST,
            border_radius_px=ControlHeight.DEFAULT.value // 2,
        )
        self._monitor_button.setFixedSize(ControlHeight.DEFAULT.value, ControlHeight.DEFAULT.value)
        self._monitor_button.setAccessibleName("Toggle screen monitoring")
        self._monitor_button.setToolTip("Enable or pause screen monitoring")
        self._monitor_button.clicked.connect(lambda: self.set_screen_monitoring(not self._screen_monitoring))

        self._stop_speech_button = AashiButton(
            "■",
            theme_manager,
            ButtonVariant.GHOST,
            border_radius_px=ControlHeight.DEFAULT.value // 2,
        )
        self._stop_speech_button.setFixedSize(ControlHeight.DEFAULT.value, ControlHeight.DEFAULT.value)
        self._stop_speech_button.setAccessibleName("Emergency stop speaking")
        self._stop_speech_button.setToolTip("Stop Aashi speaking")
        self._stop_speech_button.clicked.connect(self._stop_speaking)

        self._settings_button = AashiButton(
            "⚙",
            theme_manager,
            ButtonVariant.GHOST,
            border_radius_px=ControlHeight.DEFAULT.value // 2,
        )
        self._settings_button.setFixedSize(ControlHeight.DEFAULT.value, ControlHeight.DEFAULT.value)
        self._settings_button.setAccessibleName("Open assistant settings")
        self._settings_button.setToolTip("Assistant settings and privacy controls")
        self._settings_button.clicked.connect(self._open_settings)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.viewport().setAutoFillBackground(False)

        # The message container is the scroll widget itself. Its side margins
        # are recomputed on resize (see _update_column_margins) so the
        # conversation sits in a centred, capped reading column like
        # ChatGPT: user messages on the column's right edge, replies on its left.
        self._message_container = QWidget()
        self._message_layout = QVBoxLayout(self._message_container)
        self._message_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._message_layout.setContentsMargins(
            SPACING.card_padding,
            SPACING.card_padding,
            SPACING.card_padding,
            SPACING.card_padding,
        )
        self._message_layout.setSpacing(SPACING.chat_gap + Space.SPACE_100)
        self._message_layout.addStretch(1)
        self._scroll.setWidget(self._message_container)

        # Empty-state greeting: an overlay on the viewport, shown until the
        # first message arrives (kept out of the layout so bubbles stay at
        # the top of it).
        self._empty_state = QLabel("What can I help with?", self._scroll.viewport())
        self._empty_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_state.setObjectName("aashiEmptyState")
        self._scroll.viewport().installEventFilter(self)
        # Auto-scroll is driven by the scrollbar range, which only changes once
        # the scroll content has actually been resized.
        self._scroll.verticalScrollBar().rangeChanged.connect(
            self._on_chat_range_changed
        )

        # Navigation sidebar (left side) - will be populated after repository is available
        self._sidebar = NavigationSidebar(theme_manager)
        self._header.sidebar_toggle_requested.connect(self._sidebar.toggle_collapse)
        self._sidebar.conversation_selected.connect(self._on_conversation_selected)
        self._sidebar.conversation_deleted.connect(self._on_conversation_deleted)
        self._sidebar.new_chat_requested.connect(self._on_new_chat_requested)
        self._sidebar.project_changed.connect(self._on_project_changed)
        self._sidebar.conversation_renamed.connect(self._on_conversation_renamed)
        self._sidebar.conversation_moved.connect(self._on_conversation_moved)
        self._sidebar.conversation_moved_to_new_project.connect(self._on_moved_to_new_project)
        self._sidebar.project_created.connect(self._on_project_created)
        self._sidebar.project_renamed.connect(self._on_project_renamed)
        self._sidebar.project_deleted.connect(self._on_project_deleted)
        self._sidebar.mode_changed.connect(self._on_sidebar_mode_changed)
        self._sidebar.visibility_changed.connect(self._on_sidebar_visibility_changed)

        # Chat area (right side) - header, messages, attachment preview, composer
        self._chat_area = QWidget()
        self._chat_area.setObjectName("aashiChatArea")
        self._chat_area.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        chat_layout = QVBoxLayout(self._chat_area)
        chat_layout.setContentsMargins(0, 0, 0, Space.SPACE_100)
        chat_layout.setSpacing(0)
        chat_layout.addWidget(self._header)

        controls = QWidget()
        controls.setObjectName("aashiAssistantControls")
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(SPACING.card_padding, 4, SPACING.card_padding, 4)
        controls_layout.setSpacing(4)
        self._status_label = QLabel("Ready · Talking off · Monitoring off")
        self._status_label.setObjectName("aashiTaskStatus")
        controls_layout.addWidget(self._status_label, 1)
        controls_layout.addWidget(self._mic_button)
        controls_layout.addWidget(self._screen_button)
        controls_layout.addWidget(self._monitor_button)
        controls_layout.addWidget(self._stop_speech_button)
        controls_layout.addWidget(self._settings_button)
        chat_layout.addWidget(controls)
        chat_layout.addWidget(self._scroll, 1)
        # The staged-attachment chip sits above the composer, centred in the
        # same capped column as the pill so the two stay visually aligned.
        preview_row = QHBoxLayout()
        preview_row.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        preview_row.addWidget(self._attachment_preview)
        chat_layout.addLayout(preview_row)

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
            Space.SPACE_100, Space.SPACE_100, Space.SPACE_100, Space.SPACE_100
        )
        pill.setSpacing(Space.SPACE_050)
        pill.addWidget(self._attach_button)
        pill.addWidget(self._input, 1)
        pill.addWidget(self._send_button)

        composer_row = QHBoxLayout()
        composer_row.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        composer_row.addWidget(self._composer)
        chat_layout.addLayout(composer_row)

        self._footnote = QLabel("Aashi can make mistakes. Check important info.")
        self._footnote.setObjectName("aashiFootnote")
        self._footnote.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chat_layout.addWidget(self._footnote)

        # Main layout: sidebar on left, chat area on right
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._sidebar)
        layout.addWidget(self._chat_area, 1)

        # Earlier versions created a blank chat on every launch; drop those
        # leftovers, then list the real conversations.
        try:
            self._ensure_repository().delete_empty_conversations()
        except Exception:
            pass
        self._refresh_sidebar()

        theme_manager.theme_changed.connect(self._restyle)
        self._restyle()
        self.set_screen_monitoring(self._runtime.settings.screen_monitoring_enabled, persist=False)
        if self._runtime.settings.proactive_enabled or os.environ.get(ENV_VAR_PROACTIVE_ENABLED, "").lower() in {"1", "true", "yes", "on"}:
            # Opt-in only: no proactive greeting, microphone access or screen
            # capture occurs on a default installation.
            QTimer.singleShot(1200, self._emit_startup_proactive)

    # -- layout helpers -------------------------------------------------------

    def eventFilter(self, obj, event):  # noqa: N802 (Qt override)
        if obj is self._scroll.viewport() and event.type() == QEvent.Type.Resize:
            self._update_column_margins()
        return super().eventFilter(obj, event)

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self._update_column_margins()

    def _update_column_margins(self) -> None:
        """Centre the message column and place the empty-state greeting."""
        viewport = self._scroll.viewport()
        side = max(
            SPACING.card_padding, (viewport.width() - LAYOUT.content_reading) // 2
        )
        margins = self._message_layout.contentsMargins()
        if margins.left() != side or margins.right() != side:
            self._message_layout.setContentsMargins(
                side, margins.top(), side, margins.bottom()
            )
        height = 80
        self._empty_state.setGeometry(
            0, max(0, viewport.height() // 3 - height // 2), viewport.width(), height
        )

    # -- persistence ----------------------------------------------------------

    def _ensure_repository(self) -> ConversationRepository:
        """Return the repository, opening the database on first use.

        Opening the repository never creates a conversation: an empty chat is
        not stored until the first message is sent, so launching the app or
        pressing "New chat" leaves no blank entries behind.
        """
        if self._repository is None:
            paths = resolve_paths()
            db = get_database(paths)
            self._repository = ConversationRepository(db, paths)
        return self._repository

    def _ensure_conversation(self) -> int:
        """Return the current conversation id, creating the chat if needed."""
        repo = self._ensure_repository()
        if self._conversation_id is None:
            self._conversation_id = repo.create_conversation(
                project_id=self._get_current_project_id()
            )
        return self._conversation_id

    def save_current_message(self, role: str, content: str, attachment_paths: list[str] | None = None) -> None:
        """Persist a message to the database."""
        repo = self._ensure_repository()
        conversation_id = self._ensure_conversation()
        repo.add_message(
            conversation_id,
            role,
            content,
            attachment_paths=attachment_paths,
        )

    # -- automatic naming -------------------------------------------------------

    def _name_conversation_from_question(self, question: str) -> None:
        """Name a still-untitled chat after its first question.

        The sidebar gets an instant, offline title right away; the AI then
        proposes a better short title in the background (see
        :meth:`_apply_ai_title`).
        """
        conversation_id = self._conversation_id
        if conversation_id is None:
            return
        repo = self._ensure_repository()
        conv = repo.get_conversation(conversation_id)
        if conv is None or (conv.get("title") or "").strip():
            return
        repo.update_conversation_title(
            conversation_id, titles_service.heuristic_title(question)
        )
        self._refresh_sidebar()
        if titles_service.AI_TITLES_ENABLED:
            self._title_pool.start(_TitleTask(self._ai_worker, conversation_id, question))

    def _apply_ai_title(self, conversation_id: int, title: str) -> None:
        """Replace the instant title with the AI-proposed one."""
        repo = self._ensure_repository()
        if repo.get_conversation(conversation_id) is None:
            return  # deleted while the title was being generated
        repo.update_conversation_title(conversation_id, title)
        self._refresh_sidebar()

    def load_conversation(self, conversation_id: int) -> None:
        """Load a saved conversation, restoring messages and attachments."""
        repo = self._ensure_repository()
        self._conversation_id = conversation_id
        messages = repo.get_messages(conversation_id)
        for msg in messages:
            is_user = msg["role"] == "user"
            display_text = msg["content"]
            # Show attachment labels if there were attachments
            if msg["attachments"]:
                for att in msg["attachments"]:
                    icon = "🖼" if att["mime_type"].startswith("image/") else "📎"
                    display_text += f"\n{icon} {att['original_filename']}"
            if not is_user:
                display_text = render_markdown(tidy_reply(display_text))
            self._chat_history.append(
                {"role": "user" if is_user else "assistant", "content": msg["content"]}
            )
            bubble = self.add_message(display_text, is_user=is_user)
            # Restore attachments to memory for possible re-use (e.g. "what was
            # in the image I uploaded earlier")
            if msg["attachments"]:
                bubble.setProperty("attachments", msg["attachments"])

    # -- sidebar signal handlers --------------------------------------------------

    def _on_conversation_selected(self, conversation_id: int) -> None:
        """Load the selected conversation."""
        self._clear_chat_display()
        self.load_conversation(conversation_id)
        self._sidebar.select_conversation(conversation_id)

    def _on_new_chat_requested(self) -> None:
        """Create a new conversation."""
        self._clear_chat_display()
        # The chat is created on its first message; until then there is
        # nothing to list or highlight.
        self._conversation_id = None
        self._refresh_sidebar()
        self._input.setFocus()

    def _on_conversation_deleted(self, conversation_id: int) -> None:
        """Handle conversation deletion from sidebar."""
        repo = self._ensure_repository()
        # If the deleted conversation was the current one, clear the chat
        if self._conversation_id == conversation_id:
            self._clear_chat_display()
            self._conversation_id = None
        # Delete from database
        repo.delete_conversation(conversation_id)
        # Refresh sidebar to show updated list
        self._refresh_sidebar()

    def _on_project_changed(self, project_id: int) -> None:
        """The user picked another project: show its chats and start fresh in it."""
        if self._refreshing_sidebar:
            return
        self._clear_chat_display()
        self._conversation_id = None
        self._refresh_sidebar()

    # -- chat / project management (from the sidebar menus) ---------------------------

    def _on_conversation_renamed(self, conversation_id: int, title: str) -> None:
        title = title.strip()
        if not title:
            return
        repo = self._ensure_repository()
        repo.update_conversation_title(conversation_id, title, touch=False)
        self._refresh_sidebar()

    def _on_conversation_moved(self, conversation_id: int, project_id: int) -> None:
        """Move a chat to another project.

        If it is the chat on screen, follow it into that project so it stays
        visible and highlighted; otherwise it simply leaves this project's list.
        """
        repo = self._ensure_repository()
        repo.move_conversation(conversation_id, project_id)
        if conversation_id == self._conversation_id:
            self._switch_project_silently(project_id)
        self._refresh_sidebar()

    def _on_moved_to_new_project(self, conversation_id: int, name: str) -> None:
        project_id = self._create_project(name)
        if project_id is not None:
            self._on_conversation_moved(conversation_id, project_id)

    def _create_project(self, name: str) -> int | None:
        name = name.strip()
        if not name:
            return None
        repo = self._ensure_repository()
        user_id = repo.get_or_create_default_user()
        return repo.create_project(user_id, name)

    def _on_project_created(self, name: str) -> None:
        """Create a project and open a fresh chat inside it."""
        project_id = self._create_project(name)
        if project_id is None:
            return
        self._clear_chat_display()
        self._conversation_id = None
        self._switch_project_silently(project_id)
        self._refresh_sidebar()
        self._input.setFocus()

    def _on_project_renamed(self, project_id: int, name: str) -> None:
        name = name.strip()
        if not name:
            return
        self._ensure_repository().update_project(project_id, name=name)
        self._refresh_sidebar()
        self._sidebar.refresh_caption()

    def _on_project_deleted(self, project_id: int) -> None:
        """Delete a project; its chats move to the default project."""
        repo = self._ensure_repository()
        was_current = self._get_current_project_id() == project_id
        if not repo.delete_project(project_id):
            return  # the default project cannot be deleted
        if was_current:
            user_id = repo.get_or_create_default_user()
            self._switch_project_silently(repo.get_or_create_default_project(user_id))
            self._clear_chat_display()
            self._conversation_id = None
        self._refresh_sidebar()

    def _switch_project_silently(self, project_id: int) -> None:
        """Select a project in the sidebar without the 'start a new chat' reaction."""
        self._refreshing_sidebar = True
        try:
            self._sidebar.set_current_project(project_id)
        finally:
            self._refreshing_sidebar = False

    def _on_sidebar_mode_changed(self, mode: int) -> None:
        """Handle sidebar mode change (compact/expanded)."""
        # The sidebar handles its own visual changes
        pass

    def _on_sidebar_visibility_changed(self, visible: bool) -> None:
        """Handle sidebar visibility change (collapsed/expanded)."""
        # The sidebar handles its own animation
        pass

    def _refresh_sidebar(self) -> None:
        """Refresh the sidebar with current conversations and projects."""
        if self._refreshing_sidebar:
            return
        self._refreshing_sidebar = True
        try:
            repo = self._ensure_repository()
            user_id = repo.get_or_create_default_user()
            repo.get_or_create_default_project(user_id)  # a fresh install has one too
            projects = repo.list_projects(user_id)
            self._sidebar.set_projects(projects, self._get_current_project_id())

            current_project_id = self._get_current_project_id()
            conversations = repo.list_conversations(
                project_id=current_project_id, non_empty_only=True
            )
            self._sidebar.set_conversations(conversations, current_project_id)
            self._sidebar.select_conversation(self._conversation_id)
            self._sidebar.refresh_caption()
        finally:
            self._refreshing_sidebar = False

    def _get_current_project_id(self) -> int | None:
        """Get the current project ID from the sidebar or default."""
        # Try to get from sidebar's internal state
        if hasattr(self._sidebar, '_current_project_id') and self._sidebar._current_project_id is not None:
            return self._sidebar._current_project_id
        # Fall back to default project
        repo = self._ensure_repository()
        user_id = repo.get_or_create_default_user()
        return repo.get_or_create_default_project(user_id)

    def _clear_chat_display(self) -> None:
        """Clear all messages from the chat display."""
        self._finish_typewriter()
        if self._thinking_bubble is not None:
            self._remove_thinking_bubble()
        for bubble in self._messages:
            self._message_layout.removeWidget(bubble)
            # Hide and detach at once: deleteLater alone leaves the old bubble
            # painted until the event loop gets round to deleting it.
            bubble.hide()
            bubble.setParent(None)
            bubble.deleteLater()
        self._messages.clear()
        self._chat_history.clear()
        self._emotion.reset()  # a new chat starts with no carried-over mood
        self._empty_state.show()

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
        self._empty_state.hide()
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

    def _submit_message(self, *, speaker_verified: bool = True) -> None:
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

        # Persist user message with attachment
        attachment_paths = [attachment] if attachment is not None else None
        self.save_current_message("user", text, attachment_paths)
        self._name_conversation_from_question(text)

        # Structured desktop intents are executed locally and safely.  They do
        # not go through the model as prose, which prevents a model response
        # from being mistaken for an actual file or application operation.
        if attachment is None and self._runtime.supports_request(text):
            self._chat_history.append({"role": "user", "content": text})
            self._request_supported_action(text, speaker_verified=speaker_verified)
            return

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

        # No new attachment, but the user may be asking about a previously
        # uploaded image (e.g., "tell me about the image I uploaded earlier").
        # Recover it from the conversation history/DB and route through vision.
        previous_image = self._find_previous_image_attachment(text)
        if previous_image is not None:
            self._chat_history.append({"role": "user", "content": text})
            self._request_vision_reply(self._build_history_prompt(), previous_image)
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
        # Emotion layer: only expressive contexts get a short style note, sized so
        # routing is unchanged; technical/neutral prompts pass through untouched.
        prepared = self._emotion.prepare(self._build_history_prompt(), text)
        self._pending_emotion = prepared
        self._set_chat_status(TaskState.PROCESSING.value)
        self._request_reply(prepared.prompt)

    def _request_reply(self, message: str) -> None:
        """Ask the AI pool to answer ``message`` off the UI thread."""
        self._ai_pool.start(_AiTask(self._ai_worker, message))

    def _request_vision_reply(self, message: str, image_path: str | list[str]) -> None:
        """Ask the AI pool to answer ``message`` with ``image_path`` attached.

        The image(s) are read and encoded inside the worker task so the UI never
        blocks on large attachments. Runs on the same single-threaded pool as
        text requests, so replies stay ordered.

        Args:
            message: The prompt to send.
            image_path: A single path or a list of image paths.
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

    def _request_supported_action(self, message: str, *, speaker_verified: bool = True) -> None:
        """Queue one recognized local action and keep the UI responsive."""
        self._set_desktop_status(TaskState.PROCESSING.value)
        self._ai_pool.start(
            _AutomationTask(
                self._ai_worker,
                self._runtime,
                message,
                speaker_verified=speaker_verified,
            )
        )

    def _find_previous_image_attachment(self, text: str) -> str | None:
        """Find a previously uploaded image attachment referenced by ``text``.

        Scans the conversation's message bubbles (in reverse) for the most
        recent user message that carried an image attachment, and resolves it
        to its stored (app-owned) file path. Returns ``None`` when the user
        does not appear to be asking about a prior image or when the stored
        file is no longer available.

        The conversation history (``_chat_history``) only keeps text, so the
        attachment metadata is recovered from the loaded bubbles' ``attachments``
        property, which :meth:`load_conversation` populates from the database.
        """
        lowered = text.lower()
        reference_phrases = (
            "previous image",
            "that image",
            "image i uploaded",
            "photo from earlier",
            "uploaded image",
            "previous photo",
            "earlier image",
            "the image i sent",
            "the picture i",
        )
        if not any(phrase in lowered for phrase in reference_phrases):
            return None

        repo = self._ensure_repository()
        for bubble in reversed(self._messages):
            attachments = bubble.property("attachments")
            if not attachments:
                continue
            for att in attachments:
                if att.get("mime_type", "").startswith("image/"):
                    stored = repo.resolve_attachment_path(att)
                    if stored is not None:
                        return str(stored)
        return None

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

    # -- desktop assistant services ------------------------------------------

    def _refresh_status_ui(self) -> None:
        """Render independent subsystem states without collapsing them."""
        if not self._runtime.speech.available:
            talking = "unavailable"
        elif self._speech_output_failed:
            talking = "failed"
        elif not self._talking_mode:
            talking = "off"
        elif self._speech_output_verified:
            talking = "on"
        else:
            talking = "ready"
        monitoring = "on" if self._screen_monitoring else "off"
        if self._runtime.monitor is None:
            monitoring = "unavailable"
        elif self._monitor_status.casefold().startswith("failed"):
            monitoring = "failed"
        elif self._monitor_status.casefold().startswith("unavailable"):
            monitoring = "unavailable"
        self._status_label.setText(
            f"{self._task_status} · Talking {talking} · Monitoring {monitoring}"
        )
        self._status_label.setToolTip(
            " | ".join(
                (
                    f"Chat: {self._chat_status}",
                    f"Voice: {self._voice_status}",
                    f"Screen monitoring: {self._monitor_status}",
                    f"Desktop tasks: {self._desktop_status}",
                )
            )
        )

    def _set_chat_status(self, status: str) -> None:
        """Publish chat-generation status without changing voice/monitor state."""
        self._chat_status = status or TaskState.IDLE.value
        self._task_status = self._chat_status
        self._refresh_status_ui()
        self.task_status_changed.emit(self._task_status)

    def _set_desktop_status(self, status: str) -> None:
        """Publish desktop-action status independently from chat generation."""
        self._desktop_status = status or TaskState.IDLE.value
        self._task_status = self._desktop_status
        self._refresh_status_ui()
        self.task_status_changed.emit(self._task_status)

    def _set_voice_status(self, status: str) -> None:
        self._voice_status = status or "Ready"
        self._refresh_status_ui()
        self.talking_status_changed.emit(self._voice_status)

    def _set_monitor_status(self, status: str) -> None:
        self._monitor_status = status or "Ready"
        self._refresh_status_ui()
        self.screen_monitoring_status_changed.emit(self._monitor_status)

    def _set_task_status(self, status: str) -> None:
        """Backward-compatible alias for chat status updates."""
        self._set_chat_status(status)

    def _emit_startup_proactive(self) -> None:
        """Show one policy-gated startup greeting when explicitly enabled."""
        decision = self._runtime.startup_decision()
        if not decision.allowed:
            return
        for candidate in decision.candidates:
            self.add_message(candidate.message, is_user=False)
            if (
                self._talking_mode
                or self._runtime.settings.proactive_speech
                or os.environ.get("AASHI_PROACTIVE_SPEECH", "").lower()
                in {"1", "true", "yes", "on"}
            ):
                self._speech_pool.start(
                    _SpeechTask(self._ai_worker, self._runtime, text=candidate.message)
                )

    @property
    def task_status(self) -> str:
        """Current operation status shown to the user."""
        return self._task_status

    @property
    def chat_status(self) -> str:
        """Latest text-generation status."""
        return self._chat_status

    @property
    def desktop_status(self) -> str:
        """Latest structured desktop-action status."""
        return self._desktop_status

    @property
    def voice_status(self) -> str:
        """Latest speech-service status."""
        return self._voice_status

    @property
    def monitor_status(self) -> str:
        """Latest screen-monitor status."""
        return self._monitor_status

    @property
    def talking_mode(self) -> bool:
        """Whether automatic spoken replies are enabled."""
        return self._talking_mode

    @property
    def screen_monitoring(self) -> bool:
        """Whether the user has enabled screen-monitoring mode."""
        return self._screen_monitoring

    @property
    def runtime(self) -> AssistantRuntime:
        """Structured desktop runtime used by this chat surface."""
        return self._runtime

    def set_talking_mode(self, enabled: bool) -> bool:
        """Enable or disable spoken replies and update the visible state."""
        requested = bool(enabled)
        value = requested and self._runtime.speech.available
        changed = value != self._talking_mode
        self._talking_mode = value
        self._speech_output_verified = False
        self._speech_output_failed = False
        self._set_voice_status("Ready" if value or self._runtime.speech.available else "Unavailable")
        if changed or requested != value:
            self.talking_mode_changed.emit(value)
        return value

    def set_screen_monitoring(self, enabled: bool, *, persist: bool = True) -> bool:
        """Enable monitoring only when a real monitor backend is available."""
        requested = bool(enabled)
        monitor_available = bool(
            self._runtime.monitor is not None
            and getattr(self._runtime.monitor, "available", True)
        )
        value = requested and monitor_available
        changed = value != self._screen_monitoring
        self._screen_monitoring = value
        self._monitor_button.setToolTip(
            "Pause screen monitoring" if value else "Enable screen monitoring"
        )
        if self._runtime.monitor is not None:
            if value:
                self._runtime.monitor.resume()
                self._monitor_timer.start(self._runtime.settings.monitor_interval_seconds * 1000)
                self._set_monitor_status("Running")
            else:
                self._runtime.monitor.pause()
                self._monitor_timer.stop()
                self._monitor_poll_in_flight = False
                self._set_monitor_status("Paused" if not requested else "Unavailable")
        else:
            self._monitor_timer.stop()
            self._set_monitor_status("Unavailable")
        if persist:
            self._apply_settings(
                AutomationSettings.from_mapping(
                    {
                        **self._runtime.settings.to_mapping(),
                        "screen_monitoring_enabled": value,
                    }
                )
            )
        self._refresh_status_ui()
        if changed or requested != value:
            self.screen_monitoring_changed.emit(value)
        return value

    def _open_settings(self) -> None:
        """Open the settings dialog without stopping the chat surface."""
        dialog = AssistantSettingsDialog(self._runtime.settings, self._memory, self)
        dialog.settings_saved.connect(self._apply_settings)
        dialog.exec()

    def _apply_settings(self, settings: object) -> None:
        if not isinstance(settings, AutomationSettings):
            return
        normalized = self._runtime.update_settings(settings)
        self.set_screen_monitoring(normalized.screen_monitoring_enabled, persist=False)
        self._monitor_timer.setInterval(normalized.monitor_interval_seconds * 1000)
        self._refresh_status_ui()

    def _poll_screen_monitor(self) -> None:
        """Poll only while monitoring is explicitly enabled."""
        if (
            not self._screen_monitoring
            or self._runtime.monitor is None
            or self._monitor_poll_in_flight
        ):
            return
        self._monitor_poll_in_flight = True
        self._monitor_pool.start(_MonitorTask(self._ai_worker, self._runtime))

    def _handle_monitor_failure(self, message: str) -> None:
        self._monitor_poll_in_flight = False
        if not self._screen_monitoring:
            return
        self._stop_monitoring_after_failure(message)

    def _handle_monitor_observation(self, observation: object) -> None:
        self._monitor_poll_in_flight = False
        if not self._screen_monitoring:
            return
        if observation is None:
            self._set_monitor_status("Unavailable")
            return
        if not isinstance(observation, MonitoringObservation):
            self._stop_monitoring_after_failure("invalid monitor result")
            return
        if observation.status is ActionStatus.ERROR:
            self._stop_monitoring_after_failure(observation.message or "Failed")
        else:
            self._set_monitor_status("Running")
        if observation is None or observation.decision is None or not observation.decision.allowed:
            return
        for candidate in observation.decision.candidates:
            message = candidate.message
            self.add_message(message, is_user=False)
            self.save_current_message("assistant", message)
            self._chat_history.append({"role": "assistant", "content": message})
            if self._runtime.settings.proactive_speech and self._talking_mode:
                self._speech_pool.start(_SpeechTask(self._ai_worker, self._runtime, text=message))

    def _stop_monitoring_after_failure(self, message: str) -> None:
        """Fail closed so the shell cannot continue claiming monitoring is on."""
        was_active = self._screen_monitoring
        self._screen_monitoring = False
        self._monitor_timer.stop()
        self._monitor_poll_in_flight = False
        if self._runtime.monitor is not None:
            self._runtime.monitor.pause()
        if was_active:
            self.screen_monitoring_changed.emit(False)
        self._set_monitor_status(f"Failed: {message}")

    def _listen_once(self) -> None:
        """Ask the configured recognizer for one utterance."""
        if not self._runtime.settings.microphone_enabled:
            self._set_voice_status("Disabled")
            self._append_voice_message("Microphone access is disabled in Aashi settings.")
            return
        self._set_voice_status("Listening")
        self._speech_pool.start(_SpeechTask(self._ai_worker, self._runtime))

    def _stop_speaking(self) -> None:
        """Interrupt speech where the selected adapter supports interruption."""
        event = self._runtime.speech.stop()
        if event.state is SpeechState.ERROR:
            self._stop_talking_after_failure(event.error or "speech stop failed")
            self._append_voice_message(f"I couldn't stop speech: {event.error}")
        else:
            self._speech_output_verified = False
            self._speech_output_failed = False
            self._set_voice_status("Ready")

    def _handle_speech_event(self, event: object) -> None:
        if not isinstance(event, SpeechEvent):
            return
        if event.state is SpeechState.ERROR:
            if event.operation is SpeechOperation.SPEAK:
                self._stop_talking_after_failure(
                    event.error or "the configured speech adapter failed"
                )
            else:
                # Microphone recognition and spoken output are independent.
                # A failed listen must not switch off an otherwise working TTS
                # mode or mark a chat request as failed.
                self._set_voice_status(
                    f"Failed: {event.error or 'microphone recognition failed'}"
                )
            self._append_voice_message(
                f"Speech is unavailable: {event.error or 'the configured speech adapter failed.'}"
            )
            return
        if event.operation is SpeechOperation.LISTEN and event.text:
            # Show the recognized transcript in the normal composer, then route
            # it through the exact same text path as typed input.
            self._set_voice_status("Ready")
            self._input.setText(event.text)
            self._submit_message(speaker_verified=False)
        elif event.operation is SpeechOperation.LISTEN and event.state is SpeechState.DISABLED:
            self._set_voice_status("Unavailable")
            self._append_voice_message(
                "Microphone input is unavailable. Install the optional voice dependencies and check microphone permissions."
            )
        else:
            if event.operation is SpeechOperation.SPEAK and event.state is SpeechState.IDLE:
                self._speech_output_verified = True
                self._speech_output_failed = False
                self._set_voice_status("Verified")
            else:
                self._speech_output_verified = False
                self._set_voice_status("Ready")

    def _stop_talking_after_failure(self, message: str) -> None:
        """Disable spoken mode after a failed voice operation."""
        was_active = self._talking_mode
        self._talking_mode = False
        self._speech_output_verified = False
        self._speech_output_failed = True
        if was_active:
            self.talking_mode_changed.emit(False)
        self._set_voice_status(f"Failed: {message}")

    def _append_automation_reply(self, outcome: object) -> None:
        """Render a structured action's actual result as an assistant reply."""
        if not isinstance(outcome, RequestOutcome):
            self._append_error_message("The desktop action returned an invalid result.")
            return
        if not outcome.handled:
            return
        self._chat_history.append({"role": "assistant", "content": outcome.message})
        self.save_current_message("assistant", outcome.message)
        self._start_typewriter(tidy_reply(outcome.message))
        self._set_desktop_status(outcome.state.value)
        if self._talking_mode and outcome.message:
            self._speech_pool.start(_SpeechTask(self._ai_worker, self._runtime, text=outcome.message))

    def _analyze_screen_capture(self, prompt: str, capture) -> str:
        """Encode one ephemeral capture for the existing vision provider."""
        if not self._runtime.settings.allow_external_screen_analysis:
            raise RuntimeError(
                "External screen analysis is disabled in Settings. "
                "Enable it only if you approve sending the current screen to the configured vision provider."
            )
        image = capture.image
        handle = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        image_path = Path(handle.name)
        handle.close()
        try:
            if not hasattr(image, "save") or not image.save(str(image_path), "PNG"):
                raise RuntimeError("The screen image could not be encoded")
            uri = encode_image_data_uri(str(image_path))
            return _enforce_identity(fetch_vision_response(prompt, uri))
        finally:
            image_path.unlink(missing_ok=True)

    def _append_ai_reply(self, reply: str) -> None:
        """Show the assistant's reply with a typewriter effect. Runs on the UI thread.

        Any pending thinking bubble is removed first. The reply is remembered in
        the conversation history (unformatted) and then reformatted for reading
        before ONE empty assistant bubble is created and a QTimer fills it
        character by character, so the response looks like it is being typed in
        real time.
        """
        self._remove_thinking_bubble()
        reply = self._emotion.finish(reply, self._pending_emotion)
        self._pending_emotion = None
        self._chat_history.append({"role": "assistant", "content": reply})
        self.save_current_message("assistant", reply)
        # The typewriter reveals the Markdown *source* and renders each step, so
        # half-revealed text never shows broken HTML.
        self._start_typewriter(tidy_reply(reply))
        self._set_chat_status(TaskState.COMPLETED.value)
        if self._talking_mode and reply:
            self._speech_pool.start(_SpeechTask(self._ai_worker, self._runtime, text=reply))

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
        self._set_chat_status(TaskState.FAILED.value)

    def _append_voice_message(self, message: str) -> None:
        """Show a voice diagnostic without marking the chat request failed."""
        self.add_message(message, is_user=False)
        self._refresh_status_ui()

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
        bubble.hide()
        bubble.setParent(None)
        bubble.deleteLater()

    def _finish_typewriter(self) -> None:
        """Show the full text of any in-progress typewriter immediately."""
        if self._typewriter_timer is None or self._typewriter_bubble is None:
            return
        self._typewriter_timer.stop()
        self._typewriter_bubble.set_text(render_markdown(self._typewriter_text))
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
        # Short replies reveal one character per tick; long ones speed up so a
        # full structured answer never takes more than a few seconds.
        self._typewriter_step = max(
            _TYPEWRITER_CHARS_PER_TICK, -(-len(text) // _TYPEWRITER_MAX_TICKS)
        )
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
            self._typewriter_index + self._typewriter_step,
            len(self._typewriter_text),
        )
        self._typewriter_index = end
        self._typewriter_bubble.set_text(render_markdown(self._typewriter_text[:end]))
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
            # The centred column adds a layout pass, so the range can grow
            # once more after this signal; settle on the final bottom.
            QTimer.singleShot(0, self._scroll_to_end)

    def _scroll_to_end(self) -> None:
        scrollbar = self._scroll.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _restyle(self, *_: object) -> None:
        """Regenerate the window's backdrop and composer chrome."""
        theme = self._theme_manager.theme
        self.setStyleSheet(self._build_stylesheet(theme))
        self._composer.setStyleSheet(self._build_composer_stylesheet(theme))
        self._chat_area.setStyleSheet(self._build_chat_area_stylesheet(theme))

    def _build_stylesheet(self, theme: Theme) -> str:
        variables = qss_variables(theme)
        return (
            "AashiChatWindow {\n"
            f"  background-color: {variables['color.canvas']};\n"
            "}\n"
        )

    def _build_chat_area_stylesheet(self, theme: Theme) -> str:
        """Style the chat area: canvas backdrop, quiet text furniture."""
        variables = qss_variables(theme)
        return (
            "QWidget#aashiChatArea {\n"
            f"  background-color: {variables['color.canvas']};\n"
            "}\n"
            "QLabel#aashiEmptyState {\n"
            "  background: transparent;\n"
            f"  color: {variables['color.text']};\n"
            "  font-size: 28px;\n"
            "  font-weight: 600;\n"
            "}\n"
            "QLabel#aashiFootnote {\n"
            "  background: transparent;\n"
            f"  color: {variables['color.text.tertiary']};\n"
            "  font-size: 12px;\n"
            "  padding: 4px 0 4px 0;\n"
            "}\n"
            "QWidget#aashiAssistantControls {\n"
            "  background: transparent;\n"
            "}\n"
            "QLabel#aashiTaskStatus {\n"
            "  background: transparent;\n"
            f"  color: {variables['color.text.tertiary']};\n"
            "  padding-left: 4px;\n"
            "}\n"
            "QScrollBar:vertical {\n"
            "  background: transparent;\n"
            "  width: 10px;\n"
            "  margin: 2px;\n"
            "}\n"
            "QScrollBar::handle:vertical {\n"
            f"  background: {variables['color.border.strong']};\n"
            "  border-radius: 4px;\n"
            "  min-height: 32px;\n"
            "}\n"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {\n"
            "  height: 0;\n"
            "}\n"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {\n"
            "  background: transparent;\n"
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
            "  border-radius: 28px;\n"
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
