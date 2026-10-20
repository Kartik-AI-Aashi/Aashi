"""Verify that the existing chat surface reaches the structured runtime."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("pytestqt", reason="pytest-qt is required for GUI tests")

from PySide6.QtCore import Qt  # noqa: E402

from aashi.automation import AssistantRuntime, FileService, PermissionService, SpeechEvent, SpeechOperation, SpeechState  # noqa: E402
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
