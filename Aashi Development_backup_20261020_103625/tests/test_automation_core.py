"""Focused boundary tests for the Qt-free automation core."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
import subprocess

from aashi.automation import (
    Action,
    ActionKind,
    ActionRisk,
    ActionStatus,
    ApplicationLauncher,
    ContextEvidence,
    FileService,
    MemoryStore,
    MemoryValidationError,
    PathTraversalError,
    PermissionService,
    ProactiveContext,
    ProactiveDecisionEngine,
    ProactivePolicy,
    RecommendationCandidate,
    ScreenCaptureService,
    SensitiveFactError,
)


def test_permission_service_canonicalizes_roots_rejects_traversal_and_classifies_actions(
    tmp_path: Path,
) -> None:
    root = tmp_path / "authorized"
    root.mkdir()
    permissions = PermissionService([root])

    assert permissions.authorized_roots == (root.resolve(),)
    assert permissions.is_authorized(root / "notes.txt")
    assert not permissions.is_authorized(tmp_path / "outside.txt")
    with pytest.raises(PathTraversalError):
        permissions.ensure_authorized(root / "nested" / ".." / "notes.txt")

    read_decision = permissions.check(Action(ActionKind.READ_TEXT, target=root / "notes.txt"))
    edit_decision = permissions.check(Action(ActionKind.EDIT_FILE, target=root / "notes.txt"))
    assert read_decision.allowed
    assert read_decision.risk is ActionRisk.LOW
    assert not edit_decision.allowed
    assert edit_decision.requires_confirmation
    assert edit_decision.risk is ActionRisk.CONFIRMATION_REQUIRED
    assert permissions.classify("future_action") is ActionRisk.CONFIRMATION_REQUIRED


def test_file_service_preserves_ambiguous_folder_matches_and_requires_confirmation(tmp_path: Path) -> None:
    first = tmp_path / "one" / "Project"
    second = tmp_path / "two" / "Project"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    permissions = PermissionService([tmp_path])
    opened: list[Path] = []
    files = FileService(permissions, open_folder_callback=opened.append)

    located = files.locate_folder("Project")
    assert located.status is ActionStatus.AMBIGUOUS
    assert located.data == (first.resolve(), second.resolve())

    target = first / "note.txt"
    create = files.create_file(target, "hello")
    assert create.status is ActionStatus.NEEDS_CONFIRMATION
    assert not target.exists()
    assert files.create_file(target, "hello", confirmed=True).ok
    assert files.read_text(target).data == "hello"
    assert files.edit_file(target, "updated").status is ActionStatus.NEEDS_CONFIRMATION
    assert files.edit_file(target, "updated", confirmed=True).ok
    assert files.read_text(target).data == "updated"

    assert files.open_folder(first).ok
    assert opened == [first.resolve()]
    assert FileService(permissions, open_folder_callback=lambda _: False).open_folder(first).status is ActionStatus.ERROR


def test_file_service_does_not_allow_outside_paths(tmp_path: Path) -> None:
    root = tmp_path / "authorized"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("private", encoding="utf-8")
    files = FileService(PermissionService([root]))

    result = files.read_text(outside)
    assert result.status is ActionStatus.DENIED
    assert files.create_file(outside, "overwrite", confirmed=True).status is ActionStatus.DENIED


def test_launcher_uses_allowlist_injected_runner_and_separate_project_argument(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    calls: list[tuple[list[str], dict[str, Any]]] = []

    def runner(argv: list[str], **kwargs: Any) -> object:
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0)

    launcher = ApplicationLauncher(
        permissions=PermissionService([tmp_path]),
        configured_commands={"antigravity": ["antigravity-bin"]},
        runner=runner,
        which=lambda executable: f"/fake/{executable}",
    )

    result = launcher.launch("vscode", project=project, arguments=("--reuse-window", "file with spaces.py"))
    assert result.ok
    argv, kwargs = calls[0]
    assert argv == ["/fake/code", str(project.resolve()), "--reuse-window", "file with spaces.py"]
    assert kwargs == {"shell": False, "check": False}
    assert launcher.discover("antigravity").available
    assert launcher.discover("chrome").available
    assert launcher.launch("not-allowlisted").status is ActionStatus.INVALID


def test_launcher_reports_nonzero_process_result_as_failure(tmp_path: Path) -> None:
    class Completed:
        returncode = 17

    launcher = ApplicationLauncher(
        runner=lambda *_args, **_kwargs: Completed(),
        which=lambda _executable: "/fake/app",
    )

    result = launcher.launch("chrome")

    assert result.status is ActionStatus.ERROR
    assert "17" in result.message


def test_terminal_arguments_require_confirmation() -> None:
    calls: list[object] = []
    launcher = ApplicationLauncher(
        runner=lambda *args, **kwargs: calls.append((args, kwargs)) or subprocess.CompletedProcess(args[0], 0),
        which=lambda executable: f"/fake/{executable}",
    )

    blocked = launcher.launch("powershell", arguments=("-Command", "Remove-Item important"))
    allowed = launcher.launch(
        "powershell",
        arguments=("-Command", "Write-Output safe"),
        confirmed=True,
    )

    assert blocked.status is ActionStatus.NEEDS_CONFIRMATION
    assert allowed.ok
    assert len(calls) == 1


def test_memory_store_requires_approval_and_rejects_secrets(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.json")

    with pytest.raises(MemoryValidationError):
        store.save("favorite_color", "blue")
    with pytest.raises(SensitiveFactError):
        store.save("api_key", "not saved", approved=True)
    with pytest.raises(SensitiveFactError):
        store.save("preferences", {"password": "not saved"}, approved=True)

    store.save("favorite_color", "blue", approved=True)
    store.update("favorite_color", "green", approved=True)
    assert store.get("favorite_color").value == "green"  # type: ignore[union-attr]
    assert [fact.key for fact in store.list()] == ["favorite_color"]
    with pytest.raises(MemoryValidationError):
        store.delete("favorite_color")
    assert store.delete("favorite_color", approved=True)
    assert store.clear(approved=True) == 0
    document = (tmp_path / "memory.json").read_text(encoding="utf-8")
    assert '"facts": []' in document


def test_proactive_engine_applies_threshold_quiet_hours_and_cooldown() -> None:
    now = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
    current = [now]
    engine = ProactiveDecisionEngine(
        ProactivePolicy(cooldown_seconds=60, duplicate_window_seconds=300),
        clock=lambda: current[0],
    )
    candidate = RecommendationCandidate(
        title="Take a break",
        message="You have been working for a while.",
        score=0.9,
        evidence=(ContextEvidence("work_duration", 90, "timer"),),
        dedupe_key="break",
    )

    first = engine.decide(ProactiveContext(evidence=(ContextEvidence("focused", True),)), [candidate])
    assert first.status is ActionStatus.SUCCESS
    assert first.allowed
    assert len(first.evidence) == 2
    assert engine.decide([candidate]).status is ActionStatus.SUPPRESSED

    current[0] = now + timedelta(seconds=61)
    assert engine.decide([candidate]).status is ActionStatus.SUPPRESSED  # duplicate window remains active

    quiet_engine = ProactiveDecisionEngine(
        ProactivePolicy(quiet_hours=(time(22), time(7))),
        clock=lambda: datetime(2026, 10, 19, 23, tzinfo=timezone.utc),
    )
    quiet = quiet_engine.decide([candidate])
    assert quiet.status is ActionStatus.SUPPRESSED
    assert "Quiet hours" in quiet.reason


@dataclass
class FakeScreen:
    label: str
    captures: int = 0

    def name(self) -> str:
        return self.label

    def grabWindow(self, window_id: int) -> str:
        assert window_id == 0
        self.captures += 1
        return f"image:{self.label}"


class FakeScreenBackend:
    def __init__(self) -> None:
        self.items = [FakeScreen("left"), FakeScreen("right")]

    def screens(self) -> tuple[FakeScreen, ...]:
        return tuple(self.items)

    def capture(self, screen: FakeScreen) -> str:
        return screen.grabWindow(0)


def test_screen_service_uses_injected_backend_and_captures_on_demand() -> None:
    backend = FakeScreenBackend()
    service = ScreenCaptureService(backend)

    assert [screen.name for screen in service.list_screens()] == ["left", "right"]
    assert [screen.captures for screen in backend.items] == [0, 0]
    captured = service.capture_all()
    assert [result.status for result in captured] == [ActionStatus.SUCCESS, ActionStatus.SUCCESS]
    assert [result.data.image for result in captured] == ["image:left", "image:right"]
    assert [screen.captures for screen in backend.items] == [1, 1]
