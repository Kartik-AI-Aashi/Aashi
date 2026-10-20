"""Allowlisted application launching with argv-only subprocess boundaries."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import Action, ActionKind, ActionResult, ActionStatus
from .permissions import AuthorizationError, PathTraversalError, PermissionService

__all__ = [
    "ApplicationLauncher",
    "ApplicationSpec",
    "DEFAULT_APPLICATIONS",
    "SUPPORTED_APPLICATIONS",
]


SUPPORTED_APPLICATIONS: tuple[str, ...] = (
    "explorer",
    "vscode",
    "terminal",
    "powershell",
    "chrome",
    "antigravity",
)

# The first item is the Windows-primary executable.  Alternatives make the
# adapter useful in development without changing the Windows contract.
DEFAULT_APPLICATIONS: dict[str, tuple[str, ...]] = {
    "explorer": ("explorer.exe",),
    "vscode": ("code",),
    "terminal": ("wt.exe",),
    "powershell": ("powershell.exe",),
    "chrome": ("chrome.exe",),
}


@dataclass(frozen=True, slots=True)
class ApplicationSpec:
    """Discovery information for an allowlisted application."""

    name: str
    command: tuple[str, ...] | None
    available: bool
    configured: bool = False
    reason: str = ""


Runner = Callable[..., Any]
Which = Callable[[str], str | os.PathLike[str] | None]


def _command_parts(command: str | os.PathLike[str] | Sequence[str]) -> tuple[str, ...]:
    if isinstance(command, (str, os.PathLike)):
        parts = tuple(shlex.split(os.fspath(command), posix=os.name != "nt"))
    else:
        parts = tuple(command)
    if not parts or any(not isinstance(part, str) or not part or "\x00" in part for part in parts):
        raise ValueError("Application commands must contain non-empty strings without NUL bytes")
    return parts


class ApplicationLauncher:
    """Launch a small explicit application allowlist without shell parsing.

    ``runner`` defaults to :func:`subprocess.run` but is injectable for tests
    and platform adapters.  It always receives a list and ``shell=False``.
    ``antigravity`` has no guessed/default executable: it is available only
    when supplied through ``configured_commands``.
    """

    def __init__(
        self,
        *,
        permissions: PermissionService | None = None,
        configured_commands: Mapping[str, str | os.PathLike[str] | Sequence[str]] | None = None,
        runner: Runner = subprocess.run,
        which: Which = shutil.which,
    ) -> None:
        self._permissions = permissions
        self._runner = runner
        self._which = which
        self._configured: dict[str, tuple[str, ...]] = {}
        for raw_name, raw_command in (configured_commands or {}).items():
            name = self._normalize_name(raw_name)
            if name not in SUPPORTED_APPLICATIONS:
                raise ValueError(f"Unsupported application name: {raw_name!r}")
            self._configured[name] = _command_parts(raw_command)

    @staticmethod
    def _normalize_name(name: str) -> str:
        if not isinstance(name, str):
            raise ValueError("Application name must be a string")
        normalized = name.strip().lower()
        if normalized not in SUPPORTED_APPLICATIONS:
            raise ValueError(f"Unsupported application name: {name!r}")
        return normalized

    @staticmethod
    def supported_applications() -> tuple[str, ...]:
        """Return the validated application names this adapter understands."""
        return SUPPORTED_APPLICATIONS

    def discover(self, name: str) -> ApplicationSpec:
        """Discover one allowlisted application without starting it."""
        normalized = self._normalize_name(name)
        if normalized == "antigravity" and normalized not in self._configured:
            return ApplicationSpec(normalized, None, False, reason="antigravity requires an explicit configured command")
        command = self._configured.get(normalized, DEFAULT_APPLICATIONS.get(normalized))
        if command is None:
            return ApplicationSpec(normalized, None, False, reason="No command is configured")
        executable = command[0]
        resolved = self._which(executable)
        if resolved is None:
            # An absolute configured executable can be tested without PATH.
            configured_path = Path(executable).expanduser()
            if configured_path.is_absolute() and configured_path.is_file():
                resolved = configured_path
        if resolved is None:
            return ApplicationSpec(normalized, None, False, normalized in self._configured, reason=f"Executable not found: {executable}")
        return ApplicationSpec(
            normalized,
            (os.fspath(resolved), *command[1:]),
            True,
            normalized in self._configured,
        )

    def launch(
        self,
        name: str,
        *,
        project: str | os.PathLike[str] | Path | None = None,
        arguments: Sequence[str] = (),
        confirmed: bool = False,
    ) -> ActionResult:
        """Launch an allowlisted application with safe, separate argv values.

        A project path must be an existing authorized directory.  It is
        appended as one argument; it is never interpolated into a command
        string.  ``arguments`` are also passed as individual argv values and
        reject NUL bytes.
        """
        try:
            normalized = self._normalize_name(name)
        except ValueError as exc:
            return ActionResult.failure(ActionStatus.INVALID, str(exc))
        action = Action(ActionKind.LAUNCH_APPLICATION, target=Path(project) if project is not None else None, parameters={"application": normalized})
        spec = self.discover(normalized)
        if not spec.available or spec.command is None:
            status = ActionStatus.UNSUPPORTED if normalized == "antigravity" else ActionStatus.NOT_FOUND
            return ActionResult.failure(status, spec.reason, action=action)
        try:
            safe_arguments = tuple(arguments)
        except TypeError:
            return ActionResult.failure(ActionStatus.INVALID, "arguments must be an iterable of strings", action=action)
        if any(not isinstance(argument, str) or not argument or "\x00" in argument for argument in safe_arguments):
            return ActionResult.failure(ActionStatus.INVALID, "Application arguments must be non-empty strings without NUL bytes", action=action)
        if normalized in {"terminal", "powershell"} and safe_arguments:
            if not confirmed:
                return ActionResult.failure(
                    ActionStatus.NEEDS_CONFIRMATION,
                    f"Launching {normalized} with arguments requires confirmation because it may execute commands.",
                    action=action,
                )

        argv = list(spec.command)
        if project is not None:
            if self._permissions is None:
                return ActionResult.failure(ActionStatus.DENIED, "A permission service is required for project paths.", action=action)
            try:
                project_path = self._permissions.ensure_authorized(project, allow_missing=False)
            except PathTraversalError as exc:
                return ActionResult.failure(ActionStatus.DENIED, str(exc), action=action, error="path_traversal")
            except (AuthorizationError, FileNotFoundError) as exc:
                return ActionResult.failure(ActionStatus.DENIED, str(exc), action=action)
            if not project_path.is_dir():
                return ActionResult.failure(ActionStatus.INVALID, "The project path must be a directory.", action=action)
            argv.append(os.fspath(project_path))
        argv.extend(safe_arguments)
        try:
            completed = self._runner(argv, shell=False, check=False)
        except OSError as exc:
            return ActionResult.failure(ActionStatus.ERROR, f"Could not launch {normalized}: {exc}", action=action, error=str(exc))
        return_code = getattr(completed, "returncode", None)
        if not isinstance(return_code, int):
            return ActionResult.failure(
                ActionStatus.ERROR,
                f"{normalized} launch returned no verifiable process result.",
                action=action,
                error="missing_returncode",
                data=completed,
            )
        if isinstance(return_code, int) and return_code != 0:
            return ActionResult.failure(
                ActionStatus.ERROR,
                f"{normalized} reported exit code {return_code}.",
                action=action,
                error=f"returncode={return_code}",
                data=completed,
            )
        return ActionResult.success(completed, message=f"Launch requested for {normalized}.", action=action)
