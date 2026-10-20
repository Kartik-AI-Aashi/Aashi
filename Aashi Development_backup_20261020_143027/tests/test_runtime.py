"""Integration tests for the structured request router."""

from __future__ import annotations

from pathlib import Path
import subprocess

from aashi.automation import (
    ActionStatus,
    ApplicationLauncher,
    AssistantRuntime,
    FileService,
    PermissionService,
    ScreenCaptureService,
)


def _runtime(root: Path, opened: list[Path] | None = None) -> AssistantRuntime:
    permissions = PermissionService([root])
    callback = opened.append if opened is not None else lambda _: True
    files = FileService(permissions, open_folder_callback=callback)
    launcher = ApplicationLauncher(
        permissions=permissions,
        runner=lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0),
        which=lambda executable: f"/fake/{executable}",
    )
    return AssistantRuntime(permissions=permissions, files=files, launcher=launcher)


def test_runtime_executes_folder_listing_and_reports_real_entries(tmp_path: Path) -> None:
    project = tmp_path / "HIH"
    project.mkdir()
    (project / "README.md").write_text("hello", encoding="utf-8")
    runtime = _runtime(tmp_path)

    outcome = runtime.execute_request("Tell me what's inside HIH")

    assert outcome.handled
    assert outcome.result is not None
    assert outcome.result.status is ActionStatus.SUCCESS
    assert "README.md" in outcome.message


def test_runtime_preserves_ambiguous_folder_choice(tmp_path: Path) -> None:
    (tmp_path / "one" / "HIH").mkdir(parents=True)
    (tmp_path / "two" / "HIH").mkdir(parents=True)
    runtime = _runtime(tmp_path)

    outcome = runtime.execute_request("Open HIH folder")

    assert outcome.handled
    assert outcome.result is not None
    assert outcome.result.status is ActionStatus.AMBIGUOUS
    assert "one" in outcome.message and "two" in outcome.message


def test_runtime_launches_project_with_structured_arguments(tmp_path: Path) -> None:
    project = tmp_path / "HIH"
    project.mkdir()
    calls: list[tuple[list[str], dict[str, object]]] = []
    permissions = PermissionService([tmp_path])
    files = FileService(permissions, open_folder_callback=lambda _: True)

    def runner(argv: list[str], **kwargs: object) -> object:
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0)

    launcher = ApplicationLauncher(
        permissions=permissions,
        runner=runner,
        which=lambda executable: f"/fake/{executable}",
    )
    runtime = AssistantRuntime(permissions=permissions, files=files, launcher=launcher)

    outcome = runtime.execute_request("Open HIH in VS Code")

    assert outcome.result is not None and outcome.result.ok
    assert calls == [(["/fake/code", str(project.resolve())], {"shell": False, "check": False})]


def test_runtime_does_not_treat_conversation_as_a_desktop_action(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)

    outcome = runtime.execute_request("List some steps for me")

    assert not outcome.handled


def test_runtime_screen_request_is_explicit_and_provider_independent(tmp_path: Path) -> None:
    class Backend:
        def screens(self):
            return ("screen",)

        def capture(self, screen):
            return "image"

    permissions = PermissionService([tmp_path])
    runtime = AssistantRuntime(
        permissions=permissions,
        screen=ScreenCaptureService(Backend()),
        vision_analyzer=lambda prompt, capture: f"Analyzed: {prompt} ({capture.image})",
    )

    outcome = runtime.execute_request("Look at my screen")

    assert outcome.handled
    assert outcome.result is not None and outcome.result.ok
    assert "Analyzed" in outcome.message


def test_runtime_read_and_confirm_file_creation_workflow(tmp_path: Path) -> None:
    project = tmp_path / "HIH"
    project.mkdir()
    (project / "README.md").write_text("hello project", encoding="utf-8")
    runtime = _runtime(tmp_path)

    read = runtime.execute_request("Read README.md in HIH")
    pending = runtime.execute_request("Create file notes.txt in HIH containing first note")
    created = runtime.execute_request("yes")

    assert read.result is not None and read.result.ok
    assert "hello project" in read.message
    assert pending.state.value == "Waiting for permission"
    assert pending.result is not None and pending.result.status is ActionStatus.NEEDS_CONFIRMATION
    assert created.result is not None and created.result.ok
    assert (project / "notes.txt").read_text(encoding="utf-8") == "first note"
