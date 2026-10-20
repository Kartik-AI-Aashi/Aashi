"""Explicit JSON memory for approved, non-sensitive user facts only."""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

__all__ = [
    "MemoryFact",
    "MemoryStore",
    "MemoryValidationError",
    "SensitiveFactError",
]


class MemoryValidationError(ValueError):
    """Raised when a fact is malformed or not explicitly approved."""


class SensitiveFactError(MemoryValidationError):
    """Raised when a fact appears to contain a secret or sensitive credential."""


@dataclass(frozen=True, slots=True)
class MemoryFact:
    """One user-approved non-sensitive fact."""

    key: str
    value: Any
    created_at: str
    updated_at: str


_SENSITIVE_NAME_RE = re.compile(
    r"(?:^|[_\- .])(?:password|passwd|secret|token|api[_\- ]?key|access[_\- ]?key|private[_\- ]?key|client[_\- ]?secret|credential|bearer)(?:$|[_\- .])",
    re.IGNORECASE,
)
_SENSITIVE_VALUE_RE = re.compile(
    r"(?:-----BEGIN [^-]+ PRIVATE KEY-----|\bBearer\s+[A-Za-z0-9._~+/=-]+|\b(?:sk|pk)_[A-Za-z0-9]{12,}\b|https?://[^\s:@]+:[^\s@]+@)",
    re.IGNORECASE,
)
_SENSITIVE_TEXT_RE = re.compile(
    r"\b(?:password|passwd|secret|token|api[_\- ]?key|access[_\- ]?key|private[_\- ]?key|credential)\b\s*(?:is|=|:)",
    re.IGNORECASE,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _contains_sensitive(value: Any, *, field_name: str = "") -> bool:
    if field_name and _SENSITIVE_NAME_RE.search(field_name):
        return True
    if isinstance(value, str):
        return bool(_SENSITIVE_VALUE_RE.search(value) or _SENSITIVE_TEXT_RE.search(value))
    if isinstance(value, Mapping):
        return any(_contains_sensitive(item, field_name=str(key)) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return any(_contains_sensitive(item) for item in value)
    return False


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value)
    except (TypeError, ValueError) as exc:
        raise MemoryValidationError("Memory values must be JSON-serializable") from exc
    return value


class MemoryStore:
    """Small explicit JSON store with no implicit conversation persistence.

    A fact is written only when ``approved=True`` and after recursive secret
    detection.  The JSON file is replaced atomically after every mutation, so
    a partial write cannot become the next memory document.
    """

    _VERSION = 1

    def __init__(self, path: str | os.PathLike[str] | Path) -> None:
        self._path = Path(path).expanduser()

    @property
    def path(self) -> Path:
        """JSON file used by this store."""
        return self._path

    def _read(self) -> dict[str, Any]:
        if not self._path.exists():
            return {"version": self._VERSION, "facts": []}
        try:
            document = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise MemoryValidationError(f"Could not read memory JSON: {exc}") from exc
        if not isinstance(document, dict) or document.get("version") != self._VERSION or not isinstance(document.get("facts"), list):
            raise MemoryValidationError("Memory JSON has an unsupported format")
        return document

    def _facts(self) -> list[MemoryFact]:
        facts: list[MemoryFact] = []
        for raw in self._read()["facts"]:
            if not isinstance(raw, dict) or not all(key in raw for key in ("key", "value", "created_at", "updated_at")):
                raise MemoryValidationError("Memory JSON contains an invalid fact")
            key = self._validate_key(raw["key"])
            value = _json_safe(raw["value"])
            if _contains_sensitive(value, field_name=key):
                raise SensitiveFactError("Sensitive or credential-like facts are not stored")
            if not isinstance(raw["created_at"], str) or not isinstance(raw["updated_at"], str):
                raise MemoryValidationError("Memory timestamps must be strings")
            facts.append(MemoryFact(key, value, raw["created_at"], raw["updated_at"]))
        return facts

    def _write(self, facts: list[MemoryFact]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        document = {"version": self._VERSION, "facts": [asdict(fact) for fact in facts]}
        handle = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self._path.parent,
            prefix=f".{self._path.name}.",
            suffix=".tmp",
            delete=False,
        )
        temporary_path = Path(handle.name)
        try:
            with handle:
                json.dump(document, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self._path)
        finally:
            temporary_path.unlink(missing_ok=True)

    @staticmethod
    def _validate_key(key: str) -> str:
        if not isinstance(key, str) or not key.strip() or len(key.strip()) > 128:
            raise MemoryValidationError("Memory keys must be non-empty strings of at most 128 characters")
        normalized = key.strip()
        if _SENSITIVE_NAME_RE.search(normalized):
            raise SensitiveFactError("Memory keys may not identify secrets or credentials")
        return normalized

    @staticmethod
    def _validate_value(key: str, value: Any, approved: bool) -> Any:
        if not approved:
            raise MemoryValidationError("Saving a memory fact requires explicit user approval")
        safe_value = _json_safe(value)
        if _contains_sensitive(safe_value, field_name=key):
            raise SensitiveFactError("Sensitive or credential-like facts are not stored")
        return safe_value

    def list(self) -> tuple[MemoryFact, ...]:
        """Return all stored facts in file order."""
        return tuple(self._facts())

    def get(self, key: str) -> MemoryFact | None:
        """Return one fact by exact key, if present."""
        normalized = self._validate_key(key)
        return next((fact for fact in self._facts() if fact.key == normalized), None)

    def save(self, key: str, value: Any, *, approved: bool = False) -> MemoryFact:
        """Create or replace a fact after explicit approval and validation."""
        normalized = self._validate_key(key)
        safe_value = self._validate_value(normalized, value, approved)
        facts = self._facts()
        now = _utc_now()
        existing = next((fact for fact in facts if fact.key == normalized), None)
        updated = MemoryFact(normalized, safe_value, existing.created_at if existing else now, now)
        if existing is None:
            facts.append(updated)
        else:
            facts[facts.index(existing)] = updated
        self._write(facts)
        return updated

    def update(self, key: str, value: Any, *, approved: bool = False) -> MemoryFact:
        """Update an existing fact, requiring explicit approval."""
        normalized = self._validate_key(key)
        if self.get(normalized) is None:
            raise KeyError(normalized)
        return self.save(normalized, value, approved=approved)

    def delete(self, key: str, *, approved: bool = False) -> bool:
        """Delete one fact after explicit user approval."""
        if not approved:
            raise MemoryValidationError("Deleting a memory fact requires explicit user approval")
        normalized = self._validate_key(key)
        facts = self._facts()
        remaining = [fact for fact in facts if fact.key != normalized]
        if len(remaining) == len(facts):
            return False
        self._write(remaining)
        return True

    def clear(self, *, approved: bool = False) -> int:
        """Delete all saved facts after explicit user approval."""
        if not approved:
            raise MemoryValidationError("Clearing memory requires explicit user approval")
        facts = self._facts()
        if facts:
            self._write([])
        return len(facts)
