"""Reusable desktop window shell for Aashi.

The shell owns desktop concerns that do not belong to the conversation view:
window presentation, tray actions, application-scoped keyboard activation and
the small amount of desktop state that should remain available while the chat
surface is hidden.  An :class:`AashiChatWindow` (or another ``QWidget``) is
passed in and remains the shell's central widget; this module does not create a
second application or conversation window.

Tray support is deliberately best-effort.  The same shell can be used on
platforms without a tray, in an offscreen test process, or with a small fake
tray supplied by a test or host application.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QCloseEvent, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QMenu,
    QWidget,
)

try:  # Some Qt builds expose the widgets module without a usable tray class.
    from PySide6.QtWidgets import QSystemTrayIcon
except ImportError:  # pragma: no cover - depends on the installed Qt build
    QSystemTrayIcon = None  # type: ignore[assignment,misc]

__all__ = ["AashiDesktopWindow", "DEFAULT_SHORTCUT_SEQUENCE"]


DEFAULT_SHORTCUT_SEQUENCE = "Ctrl+Shift+A"
"""Application-scoped shortcut used to bring the shell to the foreground."""

TrayFactory = Callable[..., object]
TrayAvailability = bool | Callable[[], bool]


class AashiDesktopWindow(QMainWindow):
    """Desktop shell around an existing Aashi central widget.

    Args:
        central_widget: The existing chat surface.  It is installed unchanged
            as the ``QMainWindow`` central widget.
        parent: Optional Qt parent.
        tray_icon_factory: Optional factory or tray instance.  A factory is
            normally called with this shell as its only argument.  Supplying a
            factory makes tray behavior testable without a real desktop tray.
        tray_available: Optional availability override.  It may be a boolean
            or a zero-argument callable.  When omitted, the platform Qt tray
            availability is queried, unless a custom factory was supplied.
        shortcut_sequence: A ``QKeySequence`` or text accepted by Qt.  Invalid
            or empty sequences safely fall back to ``Ctrl+Shift+A``.
        hide_on_close: If true (the default), a normal close request hides the
            shell and leaves the application running.  :meth:`quit` is the
            explicit exit path.
        compact_size: Size used when entering compact floating mode.
        tray_factory: Alias for ``tray_icon_factory`` for hosts that prefer the
            shorter name.

    The class does not create ``QApplication``.  The host owns the one Qt
    application instance and may wrap the already-created ``AashiChatWindow``
    with this shell.
    """

    talking_mode_changed = Signal(bool)
    screen_monitoring_changed = Signal(bool)
    task_status_changed = Signal(str)
    state_changed = Signal()

    def __init__(
        self,
        central_widget: QWidget | None = None,
        parent: QWidget | None = None,
        *,
        tray_icon_factory: TrayFactory | object | None = None,
        tray_available: TrayAvailability | None = None,
        shortcut_sequence: str | QKeySequence | None = DEFAULT_SHORTCUT_SEQUENCE,
        hide_on_close: bool = True,
        compact_size: tuple[int, int] = (420, 640),
        tray_factory: TrayFactory | object | None = None,
    ) -> None:
        super().__init__(parent)

        if central_widget is None:
            central_widget = QWidget(self)
        self.setCentralWidget(central_widget)

        self.setWindowTitle("Aashi")
        self._hide_on_close = bool(hide_on_close)
        self._quitting = False
        self._compact_mode = False
        self._compact_size = self._normalise_compact_size(compact_size)
        self._full_window_flags = self.windowFlags()
        self._full_geometry = self.geometry()

        self._talking_mode = False
        self._screen_monitoring = False
        self._talking_status: str | None = None
        self._monitoring_status: str | None = None
        self._task_status = "Idle"

        # A status-bar label keeps these values visible even when no tray is
        # available.  The public properties below are the stable programmatic
        # interface for the same state.
        self._state_label = QLabel(self)
        self._state_label.setObjectName("desktopShellState")
        self._state_label.setTextFormat(Qt.TextFormat.PlainText)
        self.statusBar().addPermanentWidget(self._state_label)

        self._create_actions()
        self._update_state_ui()

        self._tray_icon: object | None = None
        self._tray_available = False
        selected_factory = tray_icon_factory
        if selected_factory is None:
            selected_factory = tray_factory
        self._setup_tray(selected_factory, tray_available)

        self._shortcut = QShortcut(self._coerce_shortcut(shortcut_sequence), self)
        self._shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._shortcut.activated.connect(self.bring_to_foreground)

    # ── Public state -------------------------------------------------------

    @property
    def talking_mode(self) -> bool:
        """Whether Aashi's talking mode is enabled."""

        return self._talking_mode

    @property
    def is_talking_mode(self) -> bool:
        """Alias useful to callers that prefer a predicate-style name."""

        return self.talking_mode

    @property
    def screen_monitoring(self) -> bool:
        """Whether screen monitoring is enabled."""

        return self._screen_monitoring

    @property
    def is_screen_monitoring(self) -> bool:
        """Alias useful to callers that prefer a predicate-style name."""

        return self.screen_monitoring

    @property
    def task_status(self) -> str:
        """Current user-visible task status."""

        return self._task_status

    @property
    def state_label(self) -> QLabel:
        """Label displaying the current desktop state."""

        return self._state_label

    @property
    def state_summary(self) -> str:
        """Human-readable summary used by the status bar and tray."""

        talking = self._effective_mode_label(
            self._talking_mode, self._talking_status, active_label="On"
        )
        monitoring = self._effective_mode_label(
            self._screen_monitoring, self._monitoring_status, active_label="On"
        )
        return (
            f"Talking mode: {talking} | Screen monitoring: {monitoring} | "
            f"Task status: {self._task_status}"
        )

    @staticmethod
    def _effective_mode_label(
        enabled: bool,
        status: str | None,
        *,
        active_label: str,
    ) -> str:
        """Convert a subsystem status into a truthful compact shell label."""
        if status is None:
            return active_label if enabled else "Off"
        lowered = status.casefold()
        if lowered.startswith("unavailable"):
            return "Unavailable"
        if lowered.startswith("failed"):
            return "Failed"
        if enabled and lowered in {"verified", "running"}:
            return active_label
        if enabled:
            return "Ready"
        return "Off"

    def set_talking_mode(self, enabled: bool) -> bool:
        """Set talking mode and return its resulting value."""

        value = bool(enabled)
        changed = value != self._talking_mode
        self._talking_mode = value
        self.talking_action.setChecked(value)
        if changed:
            self.talking_mode_changed.emit(value)
        self._update_state_ui()
        return value

    def set_talking_status(self, status: object) -> str:
        """Set the detailed speech status used by the shell summary."""
        self._talking_status = str(status) or "Ready"
        self._update_state_ui()
        return self._talking_status

    def toggle_talking_mode(self, enabled: bool | None = None) -> bool:
        """Toggle talking mode, or set it when ``enabled`` is provided."""

        return self.set_talking_mode(
            not self._talking_mode if enabled is None else enabled
        )

    def set_screen_monitoring(self, enabled: bool) -> bool:
        """Set screen monitoring and return its resulting value."""

        value = bool(enabled)
        changed = value != self._screen_monitoring
        self._screen_monitoring = value
        self.monitoring_action.setChecked(value)
        if changed:
            self.screen_monitoring_changed.emit(value)
        self._update_state_ui()
        return value

    def set_monitoring_status(self, status: object) -> str:
        """Set the detailed screen-monitor status used by the shell summary."""
        self._monitoring_status = str(status) or "Ready"
        self._update_state_ui()
        return self._monitoring_status

    def toggle_screen_monitoring(self, enabled: bool | None = None) -> bool:
        """Toggle screen monitoring, or set it when ``enabled`` is provided."""

        return self.set_screen_monitoring(
            not self._screen_monitoring if enabled is None else enabled
        )

    def set_task_status(self, status: object) -> str:
        """Set and return the task status shown in the shell."""

        value = str(status)
        if not value:
            value = "Idle"
        changed = value != self._task_status
        self._task_status = value
        self._update_state_ui()
        if changed:
            self.task_status_changed.emit(value)
        return value

    def update_task_status(self, status: object) -> str:
        """Readable alias for :meth:`set_task_status`."""

        return self.set_task_status(status)

    # ── Actions and tray ---------------------------------------------------

    @property
    def tray_icon(self) -> object | None:
        """The active tray object, or ``None`` when tray support is absent."""

        return self._tray_icon

    @property
    def tray_available(self) -> bool:
        """Whether a tray object was successfully configured."""

        return self._tray_available

    @property
    def shortcut(self) -> QShortcut:
        """Application-scoped shortcut used to reopen the shell."""

        return self._shortcut

    @property
    def shortcut_sequence(self) -> QKeySequence:
        """The currently configured shortcut sequence."""

        return self._shortcut.key()

    @property
    def compact_mode(self) -> bool:
        """Whether the shell is currently in compact floating mode."""

        return self._compact_mode

    @property
    def is_compact_mode(self) -> bool:
        """Alias for :attr:`compact_mode`."""

        return self.compact_mode

    def _create_actions(self) -> None:
        self.open_action = QAction("Open", self)
        self.open_action.setObjectName("openAction")
        self.open_action.triggered.connect(self.bring_to_foreground)

        self.hide_action = QAction("Hide", self)
        self.hide_action.setObjectName("hideAction")
        self.hide_action.triggered.connect(self.hide_to_tray)

        self.talking_action = QAction("Toggle talking mode", self)
        self.talking_action.setObjectName("toggleTalkingAction")
        self.talking_action.setCheckable(True)
        self.talking_action.triggered.connect(self.set_talking_mode)

        self.monitoring_action = QAction("Toggle screen monitoring", self)
        self.monitoring_action.setObjectName("toggleScreenMonitoringAction")
        self.monitoring_action.setCheckable(True)
        self.monitoring_action.triggered.connect(self.set_screen_monitoring)

        self.compact_action = QAction("Compact floating mode", self)
        self.compact_action.setObjectName("compactModeAction")
        self.compact_action.setCheckable(True)
        self.compact_action.triggered.connect(self.set_compact_mode)

        self.task_status_action = QAction("Task status: Idle", self)
        self.task_status_action.setObjectName("taskStatusAction")
        self.task_status_action.triggered.connect(self._show_task_status)

        self.exit_action = QAction("Exit", self)
        self.exit_action.setObjectName("exitAction")
        self.exit_action.triggered.connect(self.quit)

        # Descriptive aliases make the actions discoverable without requiring
        # callers to know the shorter internal attribute names.
        self.toggle_talking_action = self.talking_action
        self.toggle_screen_monitoring_action = self.monitoring_action
        self.talking_mode_action = self.talking_action
        self.screen_monitoring_action = self.monitoring_action

        self.tray_menu = QMenu(self)
        self.tray_menu.setObjectName("aashiTrayMenu")
        self.tray_menu.addAction(self.open_action)
        self.tray_menu.addAction(self.hide_action)
        self.tray_menu.addSeparator()
        self.tray_menu.addAction(self.talking_action)
        self.tray_menu.addAction(self.monitoring_action)
        self.tray_menu.addAction(self.compact_action)
        self.tray_menu.addAction(self.task_status_action)
        self.tray_menu.addSeparator()
        self.tray_menu.addAction(self.exit_action)

        self.tray_actions = {
            "open": self.open_action,
            "hide": self.hide_action,
            "talking": self.talking_action,
            "screen_monitoring": self.monitoring_action,
            "compact_mode": self.compact_action,
            "task_status": self.task_status_action,
            "exit": self.exit_action,
        }

    def _setup_tray(
        self,
        tray_factory: TrayFactory | object | None,
        tray_available: TrayAvailability | None,
    ) -> None:
        if tray_available is None:
            # A supplied factory is an explicit request to inject a tray and is
            # therefore usable in offscreen tests even when Qt reports no host
            # tray.  The default path still respects platform availability.
            available = tray_factory is not None and tray_factory is not QSystemTrayIcon
            if not available:
                available = self._platform_tray_available()
        else:
            available = self._resolve_tray_availability(tray_available)

        if not available:
            return

        try:
            tray = self._build_tray(tray_factory)
            if tray is None:
                return
            self._configure_tray(tray)
        except Exception:
            # Tray support must never prevent the chat window from starting.
            self._tray_icon = None
            self._tray_available = False

    def _build_tray(self, tray_factory: TrayFactory | object | None) -> object | None:
        if tray_factory is not None and not callable(tray_factory):
            return tray_factory

        factory: Any = tray_factory or QSystemTrayIcon
        if factory is None:
            return None

        if factory is QSystemTrayIcon:
            return factory(QIcon(), self)

        # Custom factories conventionally accept the shell as their only
        # argument.  The fallbacks also make simple ``lambda: FakeTray()`` and
        # QSystemTrayIcon-compatible test doubles convenient.
        try:
            return factory(self)
        except TypeError:
            try:
                return factory()
            except TypeError:
                return factory(QIcon(), self)

    def _configure_tray(self, tray: object) -> None:
        set_context_menu = getattr(tray, "setContextMenu", None)
        if callable(set_context_menu):
            set_context_menu(self.tray_menu)

        set_tool_tip = getattr(tray, "setToolTip", None)
        if callable(set_tool_tip):
            set_tool_tip("Aashi")

        activated = getattr(tray, "activated", None)
        connect = getattr(activated, "connect", None)
        if callable(connect):
            connect(self._on_tray_activated)

        show = getattr(tray, "show", None)
        if callable(show):
            show()

        self._tray_icon = tray
        self._tray_available = True

    def _on_tray_activated(self, *_args: object) -> None:
        """Open on a tray activation, including simple fake tray signals."""

        self.bring_to_foreground()

    def _show_task_status(self, *_args: object) -> str:
        self.statusBar().showMessage(f"Task status: {self._task_status}", 3000)
        return self._task_status

    def _update_state_ui(self) -> None:
        summary = self.state_summary
        self._state_label.setText(summary)
        self._state_label.setToolTip(summary)
        self.task_status_action.setText(f"Task status: {self._task_status}")
        self.task_status_action.setToolTip(summary)
        self.state_changed.emit()

    # ── Window presentation -----------------------------------------------

    def bring_to_foreground(self, *_args: object) -> None:
        """Show, restore and activate the shell without creating a process."""

        if self.isMinimized() or self.isMaximized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    open = bring_to_foreground

    def hide_to_tray(self, *_args: object) -> None:
        """Hide the shell while keeping the Qt application alive."""

        self.hide()

    hide_window = hide_to_tray

    def minimize_window(self, *_args: object) -> None:
        """Minimize the shell without requesting application termination."""

        self.showMinimized()

    minimize = minimize_window
    minimize_to_tray = hide_to_tray

    def set_compact_mode(self, enabled: bool) -> bool:
        """Enter or leave compact floating mode and return the new state."""

        value = bool(enabled)
        if value == self._compact_mode:
            return value

        if value:
            self._full_geometry = self.geometry()
            was_visible = self.isVisible()
            self._compact_mode = True
            self.compact_action.setChecked(True)
            self.setWindowFlags(
                Qt.WindowType.Tool
                | Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
            )
            self.resize(*self._compact_size)
            if was_visible:
                self.show()
            self.raise_()
            self.activateWindow()
        else:
            was_visible = self.isVisible()
            self._compact_mode = False
            self.compact_action.setChecked(False)
            self.setWindowFlags(self._full_window_flags)
            if self._full_geometry.isValid():
                self.setGeometry(self._full_geometry)
            if was_visible:
                self.showNormal()
                self.raise_()
                self.activateWindow()
        return value

    def toggle_compact_mode(self) -> bool:
        """Toggle compact floating mode and return the resulting state."""

        return self.set_compact_mode(not self._compact_mode)

    def restore_full(self) -> bool:
        """Restore the normal/full window presentation."""

        return self.set_compact_mode(False)

    restore_full_window = restore_full
    restore = restore_full

    def set_shortcut_sequence(self, sequence: str | QKeySequence | None) -> QKeySequence:
        """Set the application-scoped foreground shortcut safely."""

        key = self._coerce_shortcut(sequence)
        self._shortcut.setKey(key)
        return key

    # ── Lifetime -----------------------------------------------------------

    @property
    def is_quitting(self) -> bool:
        """Whether :meth:`quit` has been requested."""

        return self._quitting

    def quit(self, *_args: object) -> None:
        """Explicitly close the shell and request the host Qt app to exit."""

        if self._quitting:
            return
        self._quitting = True
        self._hide_tray_icon()
        self.close()

        application = QApplication.instance()
        if application is not None:
            application.quit()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt API
        # If no tray exists, hiding would strand the process without a visible
        # restore or exit action.  In that case a normal close really closes.
        if self._quitting or not self._hide_on_close or not self._tray_available:
            event.accept()
            return

        event.ignore()
        self.hide_to_tray()

    def _hide_tray_icon(self) -> None:
        if self._tray_icon is None:
            return
        hide = getattr(self._tray_icon, "hide", None)
        if callable(hide):
            hide()

    # ── Small Qt/platform helpers -----------------------------------------

    @staticmethod
    def _normalise_compact_size(size: tuple[int, int]) -> tuple[int, int]:
        try:
            width, height = size
            return max(1, int(width)), max(1, int(height))
        except (TypeError, ValueError):
            return (420, 640)

    @staticmethod
    def _coerce_shortcut(sequence: str | QKeySequence | None) -> QKeySequence:
        key = QKeySequence(sequence) if sequence is not None else QKeySequence()
        if key.isEmpty():
            key = QKeySequence(DEFAULT_SHORTCUT_SEQUENCE)
        return key

    @staticmethod
    def _platform_tray_available() -> bool:
        if QSystemTrayIcon is None:
            return False
        try:
            return bool(QSystemTrayIcon.isSystemTrayAvailable())
        except Exception:
            return False

    @staticmethod
    def _resolve_tray_availability(value: TrayAvailability) -> bool:
        try:
            return bool(value() if callable(value) else value)
        except Exception:
            return False
