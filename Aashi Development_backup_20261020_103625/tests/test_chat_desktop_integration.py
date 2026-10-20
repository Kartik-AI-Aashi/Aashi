"""Verify that the existing chat surface reaches the structured runtime."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("pytestqt", reason="pytest-qt is required for GUI tests")

from PySide6.QtCore import Qt  # noqa: E402

from aashi.automation import (  # noqa: E402
    AssistantRuntime,
    FileService,
    LocalSpeechAdapter,
    PermissionService,
    SpeechEvent,
    SpeechOperation,
    SpeechService,
    SpeechState,
)
from aashi.config import AutomationSettings  # noqa: E402
from aashi.ui.themes.manager import ThemeManager  # noqa: E402
from aashi.ui.windows import chat_window  # noqa: E402
from aashi.ui.windows.chat_window import AashiChatWindow  # noqa: E402


def test_chat_routes_supported_folder_request_to_runtime(tmp_path: Path, monkeypatch, qtbot) -> None:
    (tmp_path / "HIH").mkdir()
    (tmp_path / "HIH" / "README.md").write_text("hello", encoding="utf-8")
    data_dir = tmp_path / "aashi-data"
    monkeypatch.setenv("AASHI_DATA_DIR", str(data_dir))

    permissions = PermissionService([tmp_path])
    runtime = AssistantRuntime(
        permissions=permissions,
        files=FileService(permissions, open_folder_callback=lambda _: True),
    )
    window = AashiChatWindow(ThemeManager(), runtime=runtime)
    qtbot.addWidget(window)
    window.input.setText("Tell me what's inside HIH")

    qtbot.keyClick(window.input, Qt.Key.Key_Return)

    qtbot.waitUntil(
        lambda: window.message_count == 2
        and window._typewriter_bubble is None
        and window._thinking_bubble is None,
        timeout=4000,
    )
    assert "README.md" in window._messages[-1].text
    assert window.task_status == "Completed"


def test_unknown_request_keeps_existing_model_path(tmp_path: Path, monkeypatch, qtbot) -> None:
    monkeypatch.setenv("AASHI_DATA_DIR", str(tmp_path / "aashi-data"))
    monkeypatch.setattr(chat_window, "fetch_response_hybrid", lambda message: f"reply: {message}")
    window = AashiChatWindow(ThemeManager())
    qtbot.addWidget(window)
    window.input.setText("Tell me a small joke")

    qtbot.keyClick(window.input, Qt.Key.Key_Return)

    qtbot.waitUntil(
        lambda: window.message_count == 2
        and window._typewriter_bubble is None
        and window._thinking_bubble is None,
        timeout=4000,
    )
    assert "reply: User: Tell me a small joke" in window._messages[-1].text


def test_tts_completion_is_not_submitted_as_a_new_user_message(tmp_path: Path, monkeypatch, qtbot) -> None:
    monkeypatch.setenv("AASHI_DATA_DIR", str(tmp_path / "aashi-data"))
    window = AashiChatWindow(ThemeManager())
    qtbot.addWidget(window)
    submitted: list[bool] = []
    monkeypatch.setattr(window, "_submit_message", lambda: submitted.append(True))

    window._handle_speech_event(
        SpeechEvent(SpeechState.IDLE, "assistant answer", operation=SpeechOperation.SPEAK)
    )

    assert submitted == []


def test_unavailable_backends_are_not_reported_as_active(tmp_path: Path, monkeypatch, qtbot) -> None:
    monkeypatch.setenv("AASHI_DATA_DIR", str(tmp_path / "aashi-data"))
    runtime = AssistantRuntime(
        permissions=PermissionService([tmp_path]),
        settings=AutomationSettings(screen_monitoring_enabled=True),
    )
    window = AashiChatWindow(ThemeManager(), runtime=runtime)
    qtbot.addWidget(window)

    assert window.screen_monitoring is False
    assert window.talking_mode is False
    assert "Talking unavailable" in window._status_label.text()
    assert "Monitoring unavailable" in window._status_label.text()
    assert window.set_talking_mode(True) is False
    assert window.talking_mode is False


def test_unverified_voice_confirmation_cannot_bypass_sensitive_action(tmp_path: Path) -> None:
    project = tmp_path / "Project"
    project.mkdir()
    runtime = AssistantRuntime(permissions=PermissionService([tmp_path]))

    pending = runtime.execute_request(
        "Create file notes.txt in Project containing secret",
        speaker_verified=False,
    )

    assert pending.result is not None
    assert pending.result.status.value == "needs_confirmation"
    denied = runtime.execute_request("yes", speaker_verified=False)
    assert denied.result is not None
    assert denied.result.status.value == "denied"


def test_monitor_lifecycle_and_failure_are_independent_from_chat(tmp_path: Path, monkeypatch, qtbot) -> None:
    class BrokenMonitor:
        available = True

        def resume(self) -> None:
            pass

        def pause(self) -> None:
            pass

        def set_policy(self, _policy) -> None:
            pass

        def poll(self, **_kwargs):
            raise RuntimeError("display unavailable")

    monkeypatch.setenv("AASHI_DATA_DIR", str(tmp_path / "aashi-data"))
    runtime = AssistantRuntime(
        permissions=PermissionService([tmp_path]),
        monitor=BrokenMonitor(),
    )
    window = AashiChatWindow(ThemeManager(), runtime=runtime)
    qtbot.addWidget(window)

    assert window.set_screen_monitoring(True, persist=False) is True
    assert window._monitor_timer.isActive()
    window._poll_screen_monitor()
    qtbot.waitUntil(lambda: not window._monitor_poll_in_flight, timeout=1000)

    assert window.task_status == "Idle"
    assert window.screen_monitoring is False
    assert "display unavailable" in window._monitor_status
    assert "Monitoring failed" in window._status_label.text()
    assert not window._monitor_timer.isActive()


def test_failed_speech_output_turns_talking_mode_off(tmp_path: Path, monkeypatch, qtbot) -> None:
    def broken_speak(_text: str) -> None:
        raise RuntimeError("speaker unavailable")

    monkeypatch.setenv("AASHI_DATA_DIR", str(tmp_path / "aashi-data"))
    runtime = AssistantRuntime(
        permissions=PermissionService([tmp_path]),
        speech=SpeechService(
            LocalSpeechAdapter(synthesizer=broken_speak)
        ),
    )
    window = AashiChatWindow(ThemeManager(), runtime=runtime)
    qtbot.addWidget(window)

    assert window.set_talking_mode(True) is True
    window._handle_speech_event(
        SpeechEvent(
            SpeechState.ERROR,
            error="speaker unavailable",
            operation=SpeechOperation.SPEAK,
        )
    )

    assert window.talking_mode is False
    assert window.voice_status.startswith("Failed:")
    assert "Talking failed" in window._status_label.text()
