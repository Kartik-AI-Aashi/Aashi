"""Coverage for change-aware monitoring and persisted privacy controls."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from aashi.automation import (
    ActionStatus,
    AnalysisKind,
    ContextEvidence,
    ForegroundContext,
    MemoryStore,
    MonitoringPolicy,
    ProactiveDecisionEngine,
    ScreenAnalysis,
    ScreenCaptureService,
    ScreenMonitor,
    SensitiveFactError,
)
from aashi.config import AssistantSettingsError, AutomationSettings, load_assistant_settings, save_assistant_settings


class _Foreground:
    def __init__(self) -> None:
        self.context = ForegroundContext("Code", "main.py", process_id=1)

    def current(self):
        return self.context


class _Screen:
    def __init__(self) -> None:
        self.value = b"first"
        self.calls = 0

    def screens(self):
        return ("screen",)

    def capture(self, _screen):
        self.calls += 1
        return self.value


def test_monitor_is_paused_by_default_and_suppresses_duplicate_screen_analysis() -> None:
    foreground = _Foreground()
    backend = _Screen()
    capture = ScreenCaptureService(backend)
    analyzed: list[str] = []

    def analyzer(context, image):
        analyzed.append(context.application)
        return ScreenAnalysis(
            summary="terminal says error",
            kind=AnalysisKind.ERROR,
            confidence=0.95,
            evidence=("Traceback visible",),
            recommendation="I can see a real error. Chalo root cause check karte hain.",
        )

    now = [datetime(2026, 10, 19, 12, tzinfo=timezone.utc)]
    monitor = ScreenMonitor(
        foreground=foreground,
        capture=capture,
        analyzer=analyzer,
        decision_engine=ProactiveDecisionEngine(cooldown_seconds=0, duplicate_window_seconds=300),
        policy=MonitoringPolicy(enabled=True, interval_seconds=5, analyze_external=True),
        clock=lambda: now[0],
    )

    first = monitor.poll(force=True)
    assert first.status is ActionStatus.SUCCESS
    assert first.decision is not None and first.decision.allowed
    assert analyzed == ["Code"]

    now[0] = now[0].replace(second=6)
    duplicate = monitor.poll()
    assert duplicate.status is ActionStatus.SUPPRESSED
    assert "not changed" in duplicate.message
    assert analyzed == ["Code"]

    backend.value = b"second"
    now[0] = now[0].replace(second=12)
    second = monitor.poll()
    assert second.decision is not None and second.decision.status is ActionStatus.SUPPRESSED
    # The proactive decision's duplicate key is suppressed even though the
    # pixels changed, preventing repeated warnings about the same evidence.
    assert analyzed == ["Code", "Code"]


def test_monitor_excludes_sensitive_and_configured_applications() -> None:
    foreground = _Foreground()
    foreground.context = ForegroundContext("Banking Browser", "Account password")
    backend = _Screen()
    called: list[bool] = []
    monitor = ScreenMonitor(
        foreground=foreground,
        capture=ScreenCaptureService(backend),
        analyzer=lambda *_: called.append(True) or ScreenAnalysis(summary="unsafe"),
        policy=MonitoringPolicy(enabled=True, interval_seconds=5, analyze_external=True),
    )

    result = monitor.poll(force=True)

    assert result.status is ActionStatus.SUPPRESSED
    assert "Sensitive" in result.message
    assert called == []


def test_settings_are_validated_and_persisted_atomically(tmp_path: Path) -> None:
    path = tmp_path / "assistant_settings.json"
    settings = AutomationSettings(
        proactive_enabled=True,
        screen_monitoring_enabled=True,
        monitor_interval_seconds=15,
        authorized_roots=(str(tmp_path),),
        excluded_applications=("Banking",),
        speech_language="hi-IN",
    )

    saved = save_assistant_settings(path, settings)
    loaded = load_assistant_settings(path)

    assert saved == loaded
    assert loaded.proactive_enabled
    assert loaded.speech_language == "hi-IN"
    with pytest.raises(AssistantSettingsError):
        save_assistant_settings(path, AutomationSettings(monitor_interval_seconds=1))


def test_memory_load_validates_existing_sensitive_json(tmp_path: Path) -> None:
    path = tmp_path / "memory.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "facts": [
                    {
                        "key": "api_key",
                        "value": "secret",
                        "created_at": "now",
                        "updated_at": "now",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(SensitiveFactError):
        MemoryStore(path).list()


def test_monitor_reports_capture_backend_failures_structurally() -> None:
    class Broken:
        def screens(self):
            raise RuntimeError("display unavailable")

        def capture(self, _screen):
            raise AssertionError("must not be called")

    monitor = ScreenMonitor(
        foreground=_Foreground(),
        capture=ScreenCaptureService(Broken()),
        policy=MonitoringPolicy(enabled=True, interval_seconds=5),
    )

    result = monitor.poll(force=True)

    assert result.status is ActionStatus.ERROR
    assert "enumerate" in result.message
