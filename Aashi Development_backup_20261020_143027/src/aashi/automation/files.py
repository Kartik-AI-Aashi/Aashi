"""Authorized, summary-oriented filesystem operations for Aashi."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import Action, ActionKind, ActionResult, ActionStatus
from .permissions import AuthorizationError, PathTraversalError, PermissionService

__all__ = ["FileService", "FileSummary"]


@dataclass(frozen=True, slots=True)
class FileSummary:
    """Safe metadata for one file-system entry."""

    path: Path
    name: str
    kind: str
    size: int | None = None
    modified_at: float | None = None
    child_count: int | None = None


OpenFolderCallback = Callable[[Path], Any]


class FileService:
    """Perform read operations and tightly scoped authorized file changes."""

    def __init__(
        self,
        permissions: PermissionService,
        *,
        open_folder_callback: OpenFolderCallback | None = None,
        max_read_bytes: int = 1_048_576,
        max_list_entries: int = 500,
    ) -> None:
        if max_read_bytes <= 0:
            raise ValueError("max_read_bytes must be positive")
        if max_list_entries <= 0:
            raise ValueError("max_list_entries must be positive")
        self._permissions = permissions
        self._open_folder_callback = open_folder_callback
        self._max_read_bytes = max_read_bytes
        self._max_list_entries = max_list_entries

    @property
    def permissions(self) -> PermissionService:
        """The permission service enforcing this file service's boundary."""
        return self._permissions

    @staticmethod
    def _action(kind: ActionKind, path: Path | None = None, **parameters: Any) -> Action:
        return Action(kind, target=path, parameters=parameters)

    @staticmethod
    def _summary(path: Path) -> FileSummary:
        stat = path.stat()
        if path.is_dir():
            child_count = sum(1 for _ in path.iterdir())
            return FileSummary(path, path.name or str(path), "directory", modified_at=stat.st_mtime, child_count=child_count)
        return FileSummary(path, path.name, "file", size=stat.st_size, modified_at=stat.st_mtime)

    def _authorized(self, path: str | os.PathLike[str] | Path, action: Action) -> tuple[Path | None, ActionResult | None]:
        try:
            decision = self._permissions.check(action, path)
        except PathTraversalError as exc:
            return None, ActionResult.failure(ActionStatus.DENIED, str(exc), action=action, error="path_traversal")
        if not decision.allowed:
            status = ActionStatus.NEEDS_CONFIRMATION if decision.requires_confirmation else ActionStatus.DENIED
            return None, ActionResult.failure(status, decision.reason, action=action)
        return decision.path, None

    def locate_folder(
        self,
        name: str,
        *,
        roots: Iterable[str | os.PathLike[str] | Path] | None = None,
    ) -> ActionResult:
        """Find exact folder-name matches below authorized roots.

        An ambiguous result is deliberately not collapsed to the first match;
        callers must choose from ``result.data`` before taking a follow-up
        action.
        """
        query = name.strip()
        action = self._action(ActionKind.LOCATE_FOLDER, name=query)
        if not query or Path(query).name != query:
            return ActionResult.failure(ActionStatus.INVALID, "Folder name must be a single non-empty name.", action=action)
        search_roots = self._permissions.authorized_roots if roots is None else tuple(roots)
        canonical_roots: list[Path] = []
        for root in search_roots:
            try:
                canonical_roots.append(self._permissions.ensure_authorized(root, allow_missing=False))
            except (AuthorizationError, PathTraversalError, FileNotFoundError) as exc:
                return ActionResult.failure(ActionStatus.DENIED, str(exc), action=action)

        matches: list[Path] = []
        for root in canonical_roots:
            if not root.is_dir():
                continue
            for current, directory_names, _ in os.walk(root, followlinks=False):
                current_path = Path(current)
                directory_names[:] = sorted(directory_names)
                for directory_name in directory_names:
                    candidate = current_path / directory_name
                    try:
                        canonical = self._permissions.ensure_authorized(candidate, allow_missing=False)
                    except (AuthorizationError, PathTraversalError, FileNotFoundError):
                        continue
                    if canonical.name.casefold() == query.casefold() and canonical.is_dir():
                        matches.append(canonical)
        unique_matches = tuple(dict.fromkeys(sorted(matches)))
        if not unique_matches:
            return ActionResult.failure(ActionStatus.NOT_FOUND, f"No folder named {query!r} was found.", action=action, data=())
        if len(unique_matches) > 1:
            return ActionResult.failure(
                ActionStatus.AMBIGUOUS,
                f"Found {len(unique_matches)} folders named {query!r}; choose one.",
                action=action,
                data=unique_matches,
            )
        return ActionResult.success(unique_matches, message="Folder located.", action=action)

    def list_directory(self, path: str | os.PathLike[str] | Path) -> ActionResult:
        """List immediate authorized children as :class:`FileSummary` objects."""
        requested = Path(path)
        action = self._action(ActionKind.LIST_FILES, requested)
        resolved, failure = self._authorized(requested, action)
        if failure:
            return failure
        assert resolved is not None
        if not resolved.is_dir():
            return ActionResult.failure(ActionStatus.INVALID, "The requested path is not a directory.", action=action)
        try:
            entries = []
            truncated = False
            for index, child in enumerate(sorted(resolved.iterdir(), key=lambda value: value.name.casefold())):
                if index >= self._max_list_entries:
                    truncated = True
                    break
                try:
                    authorized_child = self._permissions.ensure_authorized(child, allow_missing=False)
                    entries.append(self._summary(authorized_child))
                except (AuthorizationError, PathTraversalError, FileNotFoundError, OSError):
                    # A symlink or race that leaves the authorized tree is not
                    # exposed through a listing.
                    continue
        except OSError as exc:
            return ActionResult.failure(ActionStatus.ERROR, f"Could not list directory: {exc}", action=action, error=str(exc))
        message = "Directory listed."
        if truncated:
            message += f" Showing the first {self._max_list_entries} entries."
        return ActionResult.success(tuple(entries), message=message, action=action)

    def list_files(self, path: str | os.PathLike[str] | Path) -> ActionResult:
        """Alias for :meth:`list_directory`."""
        return self.list_directory(path)

    def inspect(self, path: str | os.PathLike[str] | Path) -> ActionResult:
        """Return a metadata summary without returning file contents."""
        requested = Path(path)
        action = self._action(ActionKind.INSPECT_PATH, requested)
        resolved, failure = self._authorized(requested, action)
        if failure:
            return failure
        assert resolved is not None
        if not resolved.exists():
            return ActionResult.failure(ActionStatus.NOT_FOUND, "Path does not exist.", action=action)
        try:
            return ActionResult.success(self._summary(resolved), message="Path inspected.", action=action)
        except OSError as exc:
            return ActionResult.failure(ActionStatus.ERROR, f"Could not inspect path: {exc}", action=action, error=str(exc))

    def inspect_path(self, path: str | os.PathLike[str] | Path) -> ActionResult:
        """Alias for :meth:`inspect`."""
        return self.inspect(path)

    def read_text(self, path: str | os.PathLike[str] | Path, *, encoding: str = "utf-8") -> ActionResult:
        """Read a bounded UTF-8-style text file inside an authorized root."""
        requested = Path(path)
        action = self._action(ActionKind.READ_TEXT, requested, encoding=encoding)
        resolved, failure = self._authorized(requested, action)
        if failure:
            return failure
        assert resolved is not None
        if not resolved.is_file():
            return ActionResult.failure(ActionStatus.INVALID, "The requested path is not a file.", action=action)
        try:
            if resolved.stat().st_size > self._max_read_bytes:
                return ActionResult.failure(ActionStatus.INVALID, "The file exceeds the configured read limit.", action=action)
            return ActionResult.success(resolved.read_text(encoding=encoding), message="Text read.", action=action)
        except (OSError, UnicodeError) as exc:
            return ActionResult.failure(ActionStatus.ERROR, f"Could not read text: {exc}", action=action, error=str(exc))

    def create_file(
        self,
        path: str | os.PathLike[str] | Path,
        content: str = "",
        *,
        encoding: str = "utf-8",
        confirmed: bool = False,
    ) -> ActionResult:
        """Create one file, requiring confirmation and an authorized parent."""
        requested = Path(path)
        action = self._action(ActionKind.CREATE_FILE, requested, encoding=encoding)
        try:
            decision = self._permissions.check(action, requested, confirmed=confirmed)
        except PathTraversalError as exc:
            return ActionResult.failure(ActionStatus.DENIED, str(exc), action=action, error="path_traversal")
        if not decision.allowed:
            status = ActionStatus.NEEDS_CONFIRMATION if decision.requires_confirmation else ActionStatus.DENIED
            return ActionResult.failure(status, decision.reason, action=action)
        assert decision.path is not None
        if decision.path.exists():
            return ActionResult.failure(ActionStatus.INVALID, "The file already exists; use edit_file.", action=action)
        if not decision.path.parent.exists() or not decision.path.parent.is_dir():
            return ActionResult.failure(ActionStatus.NOT_FOUND, "The parent directory does not exist.", action=action)
        try:
            decision.path.write_text(content, encoding=encoding, errors="strict", newline="")
        except (OSError, UnicodeError) as exc:
            return ActionResult.failure(ActionStatus.ERROR, f"Could not create file: {exc}", action=action, error=str(exc))
        return ActionResult.success(self._summary(decision.path), message="File created.", action=action)

    def edit_file(
        self,
        path: str | os.PathLike[str] | Path,
        content: str,
        *,
        encoding: str = "utf-8",
        confirmed: bool = False,
    ) -> ActionResult:
        """Replace one existing authorized regular file after confirmation."""
        requested = Path(path)
        action = self._action(ActionKind.EDIT_FILE, requested, encoding=encoding)
        try:
            decision = self._permissions.check(action, requested, confirmed=confirmed)
        except PathTraversalError as exc:
            return ActionResult.failure(ActionStatus.DENIED, str(exc), action=action, error="path_traversal")
        if not decision.allowed:
            status = ActionStatus.NEEDS_CONFIRMATION if decision.requires_confirmation else ActionStatus.DENIED
            return ActionResult.failure(status, decision.reason, action=action)
        assert decision.path is not None
        if not decision.path.is_file():
            return ActionResult.failure(ActionStatus.NOT_FOUND, "The file does not exist.", action=action)
        try:
            decision.path.write_text(content, encoding=encoding, errors="strict", newline="")
        except (OSError, UnicodeError) as exc:
            return ActionResult.failure(ActionStatus.ERROR, f"Could not edit file: {exc}", action=action, error=str(exc))
        return ActionResult.success(self._summary(decision.path), message="File edited.", action=action)

    def open_folder(self, path: str | os.PathLike[str] | Path) -> ActionResult:
        """Open an authorized folder through an injected platform callback."""
        requested = Path(path)
        action = self._action(ActionKind.OPEN_FOLDER, requested)
        resolved, failure = self._authorized(requested, action)
        if failure:
            return failure
        assert resolved is not None
        if not resolved.is_dir():
            return ActionResult.failure(ActionStatus.INVALID, "The requested path is not a directory.", action=action)
        if self._open_folder_callback is None:
            return ActionResult.failure(ActionStatus.UNSUPPORTED, "No open-folder callback is configured.", action=action)
        try:
            callback_result = self._open_folder_callback(resolved)
        except Exception as exc:  # callback belongs to an integration boundary
            return ActionResult.failure(ActionStatus.ERROR, f"Could not open folder: {exc}", action=action, error=str(exc))
        if callback_result is False:
            return ActionResult.failure(
                ActionStatus.ERROR,
                "The folder opener reported that it could not open the folder.",
                action=action,
            )
        return ActionResult.success(callback_result, message="Folder open requested.", action=action)
