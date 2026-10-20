"""Behavioral tests for the reusable Aashi desktop shell."""

from __future__ import annotations

import pytest

pytest.importorskip("pytestqt", reason="pytest-qt is required for GUI tests")

from PySide6.QtCore import QObject, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from aashi.ui.windows.desktop_shell import (  # noqa: E402
    DEFAULT_SHORTCUT_SEQUENCE,
    AashiDesktopWindow,
)


class _FakeSignal:
    def __init__(self) -> None:
        self._slots = []

    def connect(self, slot) -> None:
        self._slots.append(slot)

    def emit(self, *args) -> None:
        for slot in self._slots:
            slot(*args)


class _FakeTray(QObject):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.activated = _FakeSignal()
        self.context_menu = None
        self.tool_tip = ""
        self.visible = False

    def setContextMenu(self, menu) -> None:  # noqa: N802 - Qt-shaped fake API
        self.context_menu = menu

    def setToolTip(self, text: str) -> None:  # noqa: N802 - Qt-shaped fake API
        self.tool_tip = text

    def show(self) -> None:
        self.visible = True

    def hide(self) -> None:
        self.visible = False


@pytest.fixture
def central_widget(qtbot) -> QWidget:
    widget = QWidget()
    widget.setObjectName("existingChatWindow")
    return widget


def _shell(qtbot, central_widget, **kwargs) -> AashiDesktopWindow:
    shell = AashiDesktopWindow(central_widget, **kwargs)
    qtbot.addWidget(shell)
    return shell


def test_shell_wraps_the_existing_central_widget_without_another_qt_app(
    qtbot, central_widget
) -> None:
    application = QApplication.instance()

    shell = _shell(qtbot, central_widget, tray_available=False)

    assert shell.centralWidget() is central_widget
    assert QApplication.instance() is application
    assert shell.tray_icon is None


def test_compact_mode_can_toggle_and_restore_full_geometry(qtbot, central_widget) -> None:
    shell = _shell(
        qtbot,
        central_widget,
        tray_available=False,
        compact_size=(300, 220),
    )
    shell.resize(760, 520)
    shell.show()
    qtbot.wait(1)
    full_size = shell.size()

    assert shell.toggle_compact_mode() is True
    assert shell.compact_mode
    assert shell.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert shell.size().width() == 300
    assert shell.size().height() == 220

    assert shell.restore_full() is False
    assert not shell.compact_mode
    assert shell.size() == full_size
    assert shell.centralWidget() is central_widget


def test_state_methods_and_tray_actions_update_visible_state(qtbot, central_widget) -> None:
    shell = _shell(
        qtbot,
        central_widget,
        tray_available=True,
        tray_icon_factory=_FakeTray,
    )
    fake_tray = shell.tray_icon
    assert isinstance(fake_tray, _FakeTray)
    assert fake_tray.context_menu is shell.tray_menu
    assert fake_tray.visible

    shell.talking_action.trigger()
    shell.monitoring_action.trigger()
    shell.update_task_status("Reading a document")

    assert shell.talking_mode is True
    assert shell.screen_monitoring is True
    assert shell.task_status == "Reading a document"
    assert "Talking mode: On" in shell.state_label.text()
    assert "Screen monitoring: On" in shell.state_label.text()
    assert shell.task_status_action.text() == "Task status: Reading a document"

    # The Task status action is actionable even though it does not open a
    # second window; it reports the current state in the shell status bar.
    shell.task_status_action.trigger()
    assert "Task status: Reading a document" in shell.statusBar().currentMessage()


def test_tray_open_and_hide_actions_control_visibility(qtbot, central_widget) -> None:
    shell = _shell(
        qtbot,
        central_widget,
        tray_available=True,
        tray_icon_factory=_FakeTray,
    )
    shell.show()

    shell.hide_action.trigger()
    assert shell.isHidden()

    shell.open_action.trigger()
    assert shell.isVisible()

    shell.hide_to_tray()
    fake_tray = shell.tray_icon
    assert isinstance(fake_tray, _FakeTray)
    fake_tray.activated.emit("single-click")
    assert shell.isVisible()


def test_minimize_and_restore_keep_the_shell_in_the_same_process(
    qtbot, central_widget
) -> None:
    shell = _shell(qtbot, central_widget, tray_available=False)
    shell.show()

    shell.minimize_window()
    assert shell.isMinimized()

    shell.bring_to_foreground()
    assert shell.isVisible()
    assert not shell.isMinimized()


def test_close_hides_without_terminating_and_quit_is_explicit(
    qtbot, central_widget, monkeypatch
) -> None:
    shell = _shell(qtbot, central_widget, tray_available=False)
    shell.show()

    shell.close()
    assert shell.isHidden()
    assert not shell.is_quitting

    quit_calls: list[bool] = []
    monkeypatch.setattr(QApplication, "quit", lambda _application: quit_calls.append(True))
    shell.quit()

    assert shell.is_quitting
    assert quit_calls == [True]


def test_shortcut_is_safe_application_scoped_and_configurable(qtbot, central_widget) -> None:
    shell = _shell(qtbot, central_widget, tray_available=False)

    assert shell.shortcut_sequence.toString() == DEFAULT_SHORTCUT_SEQUENCE
    assert shell.shortcut.context().name == "ApplicationShortcut"

    shell.set_shortcut_sequence("Alt+F8")
    assert shell.shortcut_sequence.toString() == "Alt+F8"

    shell.show()
    shell.hide_to_tray()
    shell.shortcut.activated.emit()
    assert shell.isVisible()


def test_invalid_shortcut_falls_back_to_default(qtbot, central_widget) -> None:
    shell = _shell(qtbot, central_widget, tray_available=False, shortcut_sequence="")

    assert shell.shortcut_sequence.toString() == DEFAULT_SHORTCUT_SEQUENCE


def test_tray_unavailable_keeps_actions_usable(qtbot, central_widget) -> None:
    shell = _shell(qtbot, central_widget, tray_available=False)

    shell.toggle_talking_mode()
    shell.toggle_screen_monitoring()
    shell.set_task_status("Waiting")

    assert shell.tray_icon is None
    assert shell.talking_mode
    assert shell.screen_monitoring
    assert shell.task_status == "Waiting"


def test_shell_summary_distinguishes_unavailable_subsystems(qtbot, central_widget) -> None:
    shell = _shell(qtbot, central_widget, tray_available=False)

    shell.set_talking_status("Unavailable")
    shell.set_monitoring_status("Failed: display unavailable")

    assert "Talking mode: Unavailable" in shell.state_summary
    assert "Screen monitoring: Failed" in shell.state_summary
