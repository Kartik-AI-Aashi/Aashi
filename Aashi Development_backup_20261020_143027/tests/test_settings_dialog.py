"""User-facing settings and memory controls are wired to real state."""

from __future__ import annotations

import pytest

pytest.importorskip("pytestqt", reason="pytest-qt is required for GUI tests")

from aashi.automation import MemoryStore  # noqa: E402
from aashi.config import AutomationSettings  # noqa: E402
from aashi.ui.windows.settings_dialog import AssistantSettingsDialog  # noqa: E402


def test_settings_dialog_exposes_monitoring_privacy_and_memory_controls(qtbot, tmp_path) -> None:
    memory = MemoryStore(tmp_path / "memory.json")
    memory.save("preferred_language", "Hinglish", approved=True)
    dialog = AssistantSettingsDialog(
        AutomationSettings(),
        memory,
    )
    qtbot.addWidget(dialog)

    assert dialog.windowTitle() == "Aashi settings"
    assert dialog.findChildren(type(dialog._proactive))
    assert dialog._memory_list.count() == 1

    dialog._monitoring.setChecked(True)
    dialog._external_analysis.setChecked(True)
    dialog._interval.setValue(15)
    dialog._save()

    assert dialog.result() == dialog.DialogCode.Accepted
