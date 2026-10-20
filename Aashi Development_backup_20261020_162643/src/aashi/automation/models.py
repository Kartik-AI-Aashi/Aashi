"""Shared, dependency-free data models for Aashi automation.

The automation package deliberately communicates through small immutable data
objects.  UI code can render these objects later without having to know about
subprocesses, filesystem exceptions, or optional desktop integrations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

__all__ = [
    "Action",
    "ActionKind",
    "ActionResult",
    "ActionRisk",
    "ActionStatus",
]


class ActionKind(str, Enum):
    """Named operations that an automation service can perform."""

    LOCATE_FOLDER = "locate_folder"
    LIST_FILES = "list_files"
    INSPECT_PATH = "inspect_path"
    READ_TEXT = "read_text"
    CREATE_FILE = "create_file"
    EDIT_FILE = "edit_file"
    DELETE_FILE = "delete_file"
    OPEN_FOLDER = "open_folder"
    LAUNCH_APPLICATION = "launch_application"
    CAPTURE_SCREEN = "capture_screen"
    SPEECH_LISTEN = "speech_listen"
    SPEECH_SPEAK = "speech_speak"
    MEMORY_READ = "memory_read"
    MEMORY_WRITE = "memory_write"
    MEMORY_DELETE = "memory_delete"
    RUN_TESTS = "run_tests"


class ActionRisk(str, Enum):
    """Risk classification used by :class:`PermissionService`."""

    LOW = "low"
    CONFIRMATION_REQUIRED = "confirmation_required"


class ActionStatus(str, Enum):
    """Stable result statuses suitable for a future UI or API boundary."""

    SUCCESS = "success"
    NEEDS_CONFIRMATION = "needs_confirmation"
    DENIED = "denied"
    NOT_FOUND = "not_found"
    AMBIGUOUS = "ambiguous"
    INVALID = "invalid"
    UNSUPPORTED = "unsupported"
    SUPPRESSED = "suppressed"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class Action:
    """A structured request made to an automation service.

    ``parameters`` contains non-path arguments such as an application name.
    Services should still validate those arguments at their own boundary.
    """

    kind: ActionKind | str
    target: Path | None = None
    parameters: Mapping[str, Any] = field(default_factory=dict)
    description: str = ""

    @property
    def name(self) -> str:
        """Return the wire-safe action name."""
        return self.kind.value if isinstance(self.kind, ActionKind) else str(self.kind)


@dataclass(frozen=True, slots=True)
class ActionResult:
    """Outcome of an automation operation.

    ``data`` is intentionally typed as ``Any`` because each service returns a
    different immutable summary or adapter value.  Callers should branch on
    ``status`` before using it.
    """

    status: ActionStatus
    message: str = ""
    data: Any = None
    action: Action | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        """Whether the operation completed successfully."""
        return self.status is ActionStatus.SUCCESS

    @classmethod
    def success(
        cls,
        data: Any = None,
        *,
        message: str = "",
        action: Action | None = None,
    ) -> ActionResult:
        """Build a successful result."""
        return cls(ActionStatus.SUCCESS, message, data, action)

    @classmethod
    def failure(
        cls,
        status: ActionStatus,
        message: str,
        *,
        action: Action | None = None,
        error: str | None = None,
        data: Any = None,
    ) -> ActionResult:
        """Build a non-success result while preserving structured context."""
        return cls(status, message, data, action, error)
