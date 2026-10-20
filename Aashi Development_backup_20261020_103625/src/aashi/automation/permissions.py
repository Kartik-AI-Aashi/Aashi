"""Security boundary for filesystem-backed automation actions."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from .models import Action, ActionKind, ActionRisk

__all__ = [
    "AuthorizationError",
    "ConfirmationCallback",
    "PathTraversalError",
    "PermissionDecision",
    "PermissionService",
]


class AuthorizationError(PermissionError):
    """Raised when a path is outside the configured authorized roots."""


class PathTraversalError(AuthorizationError):
    """Raised when a path contains an explicit parent traversal component."""


ConfirmationCallback = Callable[[Action], bool]


@dataclass(frozen=True, slots=True)
class PermissionDecision:
    """The result of checking an action against the permission policy."""

    allowed: bool
    risk: ActionRisk
    action: Action
    path: Path | None = None
    reason: str = ""
    requires_confirmation: bool = False


_LOW_RISK_ACTIONS: Final[frozenset[ActionKind]] = frozenset(
    {
        ActionKind.LOCATE_FOLDER,
        ActionKind.LIST_FILES,
        ActionKind.INSPECT_PATH,
        ActionKind.READ_TEXT,
        ActionKind.OPEN_FOLDER,
        ActionKind.LAUNCH_APPLICATION,
        ActionKind.CAPTURE_SCREEN,
        ActionKind.SPEECH_LISTEN,
        ActionKind.SPEECH_SPEAK,
        ActionKind.MEMORY_READ,
    }
)

_DESTRUCTIVE_ACTIONS: Final[frozenset[ActionKind]] = frozenset(
    {ActionKind.CREATE_FILE, ActionKind.EDIT_FILE, ActionKind.DELETE_FILE, ActionKind.MEMORY_WRITE, ActionKind.MEMORY_DELETE}
)


def _action_kind(action: Action | ActionKind | str) -> ActionKind | None:
    if isinstance(action, Action):
        action = action.kind
    if isinstance(action, ActionKind):
        return action
    try:
        return ActionKind(str(action).strip().lower())
    except ValueError:
        return None


class PermissionService:
    """Authorize paths and classify actions before a service performs them.

    Roots are canonicalized once at construction.  Every later path is
    resolved with symlinks before comparison, so a symlink inside an allowed
    directory cannot silently grant access outside it.  A request containing
    ``..`` is rejected even when it would resolve back inside a root; this
    keeps traversal attempts explicit and auditable.

    Destructive actions are never implicitly allowed.  Pass ``confirmed=True``
    for an already approved request, or provide ``confirmation_callback`` to
    connect a future UI confirmation surface.
    """

    def __init__(
        self,
        authorized_roots: Iterable[str | os.PathLike[str] | Path],
        *,
        confirmation_callback: ConfirmationCallback | None = None,
    ) -> None:
        roots = tuple(self._canonicalize_root(Path(root)) for root in authorized_roots)
        self._authorized_roots = tuple(dict.fromkeys(roots))
        self._confirmation_callback = confirmation_callback

    @property
    def authorized_roots(self) -> tuple[Path, ...]:
        """Canonical roots used by this service."""
        return self._authorized_roots

    def set_authorized_roots(
        self,
        authorized_roots: Iterable[str | os.PathLike[str] | Path],
    ) -> tuple[Path, ...]:
        """Replace the canonical root set after an explicit settings change."""
        roots = tuple(self._canonicalize_root(Path(root)) for root in authorized_roots)
        self._authorized_roots = tuple(dict.fromkeys(roots))
        return self._authorized_roots

    @staticmethod
    def _canonicalize_root(path: Path) -> Path:
        return path.expanduser().resolve(strict=False)

    @staticmethod
    def _has_parent_traversal(path: Path) -> bool:
        return ".." in path.parts

    def canonicalize(self, path: str | os.PathLike[str] | Path) -> Path:
        """Return a canonical path, rejecting explicit traversal components."""
        candidate = Path(path).expanduser()
        if self._has_parent_traversal(candidate):
            raise PathTraversalError(f"Path traversal is not allowed: {path!s}")
        return candidate.resolve(strict=False)

    def is_authorized(self, path: str | os.PathLike[str] | Path) -> bool:
        """Return whether ``path`` is inside one of the canonical roots."""
        try:
            candidate = self.canonicalize(path)
        except (OSError, AuthorizationError):
            return False
        return any(candidate == root or root in candidate.parents for root in self._authorized_roots)

    def ensure_authorized(
        self,
        path: str | os.PathLike[str] | Path,
        *,
        allow_missing: bool = True,
    ) -> Path:
        """Canonicalize and authorize a path, raising on policy violations."""
        candidate = self.canonicalize(path)
        if not allow_missing and not candidate.exists():
            raise FileNotFoundError(candidate)
        if not any(candidate == root or root in candidate.parents for root in self._authorized_roots):
            raise AuthorizationError(f"Path is outside authorized roots: {candidate}")
        return candidate

    def classify(self, action: Action | ActionKind | str) -> ActionRisk:
        """Classify an action as low-risk or confirmation-required."""
        kind = _action_kind(action)
        if kind in _DESTRUCTIVE_ACTIONS:
            return ActionRisk.CONFIRMATION_REQUIRED
        if kind in _LOW_RISK_ACTIONS:
            return ActionRisk.LOW
        # A future or malformed operation must not receive the low-risk
        # default.  Requiring confirmation keeps additions fail-closed until
        # their policy is explicitly classified.
        return ActionRisk.CONFIRMATION_REQUIRED

    def check(
        self,
        action: Action | ActionKind | str,
        path: str | os.PathLike[str] | Path | None = None,
        *,
        confirmed: bool = False,
    ) -> PermissionDecision:
        """Return a decision without performing the requested operation.

        Unknown actions are treated as low-risk only after callers have made
        their own operation-specific validation.  This method's main safety
        guarantee is path authorization plus confirmation for known writes.
        """
        if isinstance(action, Action):
            request = action
        else:
            kind = _action_kind(action)
            request = Action(kind or str(action), target=Path(path) if path is not None else None)
        risk = self.classify(request)
        canonical_path: Path | None = None
        if path is not None or request.target is not None:
            raw_path = path if path is not None else request.target
            try:
                canonical_path = self.ensure_authorized(raw_path)  # type: ignore[arg-type]
            except PathTraversalError:
                raise
            except AuthorizationError as exc:
                return PermissionDecision(False, risk, request, reason=str(exc))

        if risk is ActionRisk.CONFIRMATION_REQUIRED and not confirmed:
            if self._confirmation_callback is None or not self._confirmation_callback(request):
                return PermissionDecision(
                    False,
                    risk,
                    request,
                    canonical_path,
                    reason="User confirmation is required for this action.",
                    requires_confirmation=True,
                )
        return PermissionDecision(True, risk, request, canonical_path, reason="Authorized.")
