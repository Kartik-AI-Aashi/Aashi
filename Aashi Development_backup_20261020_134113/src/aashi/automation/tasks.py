"""Safe supported test execution and small multi-step task plans."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from threading import Event
from typing import Any

from .models import Action, ActionKind, ActionResult, ActionStatus
from .permissions import AuthorizationError, PathTraversalError, PermissionService

__all__ = [
    "ProjectTestRunner",
    "TaskExecutionResult",
    "TaskExecutor",
    "TaskPlan",
    "TaskExecutionState",
    "TaskStep",
    "TestRunReport",
]


class TaskExecutionState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_PERMISSION = "waiting_permission"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


@dataclass(frozen=True, slots=True)
class TaskStep:
    name: str
    action: Callable[[], ActionResult]
    verify: Callable[[ActionResult], bool] | None = None


@dataclass(frozen=True, slots=True)
class TaskPlan:
    name: str
    steps: tuple[TaskStep, ...]


@dataclass(frozen=True, slots=True)
class TaskExecutionResult:
    state: TaskExecutionState
    completed_steps: tuple[str, ...] = ()
    failed_step: str | None = None
    result: ActionResult | None = None
    message: str = ""


class TaskExecutor:
    """Execute a bounded sequence with cancellation and independent verification."""

    def execute(
        self,
        plan: TaskPlan,
        *,
        cancel: Event | None = None,
        timeout_seconds: float = 120.0,
        on_step: Callable[[str, TaskExecutionState], None] | None = None,
    ) -> TaskExecutionResult:
        if not plan.steps:
            return TaskExecutionResult(TaskExecutionState.COMPLETED, message="No task steps were requested.")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        completed: list[str] = []
        stop = cancel or Event()
        for step in plan.steps:
            if stop.is_set():
                return TaskExecutionResult(TaskExecutionState.CANCELLED, tuple(completed), failed_step=step.name, message="Task cancelled.")
            if on_step:
                on_step(step.name, TaskExecutionState.RUNNING)
            pool = ThreadPoolExecutor(max_workers=1)
            try:
                future = pool.submit(step.action)
                result = future.result(timeout=timeout_seconds)
            except FutureTimeout:
                future.cancel()
                pool.shutdown(wait=False, cancel_futures=True)
                if on_step:
                    on_step(step.name, TaskExecutionState.TIMED_OUT)
                return TaskExecutionResult(TaskExecutionState.TIMED_OUT, tuple(completed), failed_step=step.name, message=f"Step '{step.name}' timed out.")
            except Exception as exc:
                pool.shutdown(wait=False, cancel_futures=True)
                if on_step:
                    on_step(step.name, TaskExecutionState.FAILED)
                failure = ActionResult.failure(ActionStatus.ERROR, f"Step '{step.name}' failed: {exc}", error=str(exc))
                return TaskExecutionResult(TaskExecutionState.FAILED, tuple(completed), failed_step=step.name, result=failure, message=failure.message)
            else:
                pool.shutdown(wait=True, cancel_futures=True)
            if not isinstance(result, ActionResult) or not result.ok:
                if on_step:
                    on_step(step.name, TaskExecutionState.FAILED)
                return TaskExecutionResult(TaskExecutionState.FAILED, tuple(completed), failed_step=step.name, result=result if isinstance(result, ActionResult) else None, message=f"Step '{step.name}' did not complete successfully.")
            if step.verify is not None:
                try:
                    verified = step.verify(result)
                except Exception as exc:
                    verified = False
                    result = ActionResult.failure(ActionStatus.ERROR, f"Step '{step.name}' verification failed: {exc}", error=str(exc), data=result.data)
                if not verified:
                    if on_step:
                        on_step(step.name, TaskExecutionState.FAILED)
                    return TaskExecutionResult(TaskExecutionState.FAILED, tuple(completed), failed_step=step.name, result=result, message=f"Step '{step.name}' could not be verified.")
            completed.append(step.name)
        return TaskExecutionResult(TaskExecutionState.COMPLETED, tuple(completed), message=f"Completed {len(completed)} task step(s).")


@dataclass(frozen=True, slots=True)
class TestRunReport:
    project: Path
    command: tuple[str, ...]
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def passed(self) -> bool:
        return self.returncode == 0 and not self.timed_out


class ProjectTestRunner:
    """Run only test commands derived from recognized project manifests."""

    def __init__(
        self,
        permissions: PermissionService,
        *,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        self._permissions = permissions
        self._runner = runner

    def supported_command(self, project: str | os.PathLike[str] | Path) -> tuple[str, ...] | None:
        path = Path(project)
        if (path / "pyproject.toml").is_file() or (path / "pytest.ini").is_file() or (path / "tests").is_dir():
            return (sys.executable, "-m", "pytest", "-q")
        package = path / "package.json"
        if package.is_file():
            try:
                document = json.loads(package.read_text(encoding="utf-8"))
                if isinstance(document, dict) and isinstance(document.get("scripts"), dict) and document["scripts"].get("test"):
                    return ("npm", "test")
            except (OSError, UnicodeError, json.JSONDecodeError):
                return None
        return None

    def run(
        self,
        project: str | os.PathLike[str] | Path,
        *,
        timeout_seconds: float = 120.0,
    ) -> ActionResult:
        action = Action(ActionKind.RUN_TESTS, target=Path(project))
        try:
            resolved = self._permissions.ensure_authorized(project, allow_missing=False)
        except (AuthorizationError, PathTraversalError, FileNotFoundError) as exc:
            return ActionResult.failure(ActionStatus.DENIED, str(exc), action=action)
        if not resolved.is_dir():
            return ActionResult.failure(ActionStatus.INVALID, "The test target must be a directory.", action=action)
        command = self.supported_command(resolved)
        if command is None:
            return ActionResult.failure(ActionStatus.UNSUPPORTED, "No supported test manifest was found.", action=action)
        try:
            completed = self._runner(
                list(command),
                cwd=os.fspath(resolved),
                shell=False,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            report = TestRunReport(resolved, command, None, str(exc.stdout or ""), str(exc.stderr or ""), True)
            return ActionResult.failure(ActionStatus.ERROR, "Tests timed out.", action=action, data=report, error="timeout")
        except OSError as exc:
            return ActionResult.failure(ActionStatus.ERROR, f"Could not run supported tests: {exc}", action=action, error=str(exc))
        report = TestRunReport(resolved, command, completed.returncode, completed.stdout or "", completed.stderr or "")
        if not report.passed:
            return ActionResult.failure(
                ActionStatus.ERROR,
                f"Tests failed with exit code {report.returncode}.",
                action=action,
                data=report,
                error=report.stderr[-2000:] or report.stdout[-2000:],
            )
        return ActionResult.success(report, message="Supported tests passed.", action=action)
