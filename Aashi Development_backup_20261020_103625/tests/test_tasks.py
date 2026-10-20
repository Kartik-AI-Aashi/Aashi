"""Supported test-runner and task-plan tests using injected processes."""

from __future__ import annotations

import subprocess
from pathlib import Path
from threading import Event
import time

from aashi.automation import (
    ActionResult,
    ActionStatus,
    PermissionService,
    ProjectTestRunner,
    TaskExecutionState,
    TaskExecutor,
    TaskPlan,
    TaskStep,
)


def test_project_test_runner_derives_pytest_command_and_reports_failure(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / "tests").mkdir(parents=True)
    calls: list[dict] = []

    def runner(argv, **kwargs):
        calls.append({"argv": argv, **kwargs})
        return subprocess.CompletedProcess(argv, 3, stdout="1 failed", stderr="")

    result = ProjectTestRunner(PermissionService([tmp_path]), runner=runner).run(project)

    assert result.status is ActionStatus.ERROR
    assert result.data.returncode == 3
    assert calls[0]["shell"] is False
    assert calls[0]["cwd"] == str(project.resolve())


def test_task_executor_verifies_each_step_and_cancels_before_next_step() -> None:
    executed: list[str] = []
    cancel = Event()

    def first() -> ActionResult:
        executed.append("first")
        cancel.set()
        return ActionResult.success("created")

    def second() -> ActionResult:
        executed.append("second")
        return ActionResult.success("should not run")

    plan = TaskPlan(
        "two-step task",
        (
            TaskStep("create", first, verify=lambda result: result.data == "created"),
            TaskStep("launch", second),
        ),
    )
    result = TaskExecutor().execute(plan, cancel=cancel)

    assert result.state is TaskExecutionState.CANCELLED
    assert result.completed_steps == ("create",)
    assert executed == ["first"]


def test_task_executor_reports_verification_failure() -> None:
    plan = TaskPlan(
        "verification",
        (TaskStep("open", lambda: ActionResult.success("requested"), verify=lambda _: False),),
    )

    result = TaskExecutor().execute(plan)

    assert result.state is TaskExecutionState.FAILED
    assert result.failed_step == "open"
