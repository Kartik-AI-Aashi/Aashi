"""Persisted, user-facing settings for Aashi's desktop-assistant features.

This file deliberately contains preferences and paths only.  Credentials stay
in environment variables or the operating system's credential facilities.
Invalid persisted values fail closed to safe defaults when loading and raise a
clear :class:`AssistantSettingsError` when a caller attempts to save them.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Mapping

__all__ = [
    "AssistantSettingsError",
    "AutomationSettings",
    "load_assistant_settings",
    "save_assistant_settings",
]


class AssistantSettingsError(ValueError):
    """Raised when assistant settings are malformed or unsafe."""


def _bool(value: object, name: str) -> bool:
    if isinstance(value, bool):
        return value
    raise AssistantSettingsError(f"{name} must be a boolean")


def _clock(value: object, name: str) -> str:
    if not isinstance(value, str) or len(value) != 5 or value[2] != ":":
        raise AssistantSettingsError(f"{name} must use HH:MM format")
    try:
        hour, minute = (int(part) for part in value.split(":"))
    except ValueError as exc:
        raise AssistantSettingsError(f"{name} must use HH:MM format") from exc
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise AssistantSettingsError(f"{name} must use a valid 24-hour time")
    return f"{hour:02d}:{minute:02d}"


@dataclass(frozen=True, slots=True)
class AutomationSettings:
    """All persisted preferences needed by the proactive desktop assistant."""

    proactive_enabled: bool = False
    proactive_speech: bool = False
    microphone_enabled: bool = False
    screen_monitoring_enabled: bool = False
    monitor_interval_seconds: int = 30
    excluded_applications: tuple[str, ...] = ()
    quiet_hours_start: str = "22:00"
    quiet_hours_end: str = "07:00"
    do_not_disturb: bool = False
    authorized_roots: tuple[str, ...] = ()
    memory_enabled: bool = True
    speech_language: str = "en-IN"
    interruptible_speech: bool = True
    allow_external_screen_analysis: bool = False
    recommendation_threshold: float = 0.82
    warning_threshold: float = 0.80
    proactive_cooldown_seconds: int = 300
    duplicate_window_seconds: int = 900

    def validate(self) -> "AutomationSettings":
        """Validate and normalize a settings object before it is persisted."""
        for name in (
            "proactive_enabled",
            "proactive_speech",
            "microphone_enabled",
            "screen_monitoring_enabled",
            "do_not_disturb",
            "memory_enabled",
            "interruptible_speech",
            "allow_external_screen_analysis",
        ):
            _bool(getattr(self, name), name)
        if not 5 <= self.monitor_interval_seconds <= 3600:
            raise AssistantSettingsError("monitor_interval_seconds must be between 5 and 3600")
        if not 0.0 <= self.recommendation_threshold <= 1.0:
            raise AssistantSettingsError("recommendation_threshold must be between 0 and 1")
        if not 0.0 <= self.warning_threshold <= 1.0:
            raise AssistantSettingsError("warning_threshold must be between 0 and 1")
        if self.proactive_cooldown_seconds < 0 or self.duplicate_window_seconds < 0:
            raise AssistantSettingsError("proactive suppression windows cannot be negative")
        _clock(self.quiet_hours_start, "quiet_hours_start")
        _clock(self.quiet_hours_end, "quiet_hours_end")
        if not isinstance(self.speech_language, str) or not self.speech_language.strip():
            raise AssistantSettingsError("speech_language must be a non-empty string")
        for name, values in (
            ("excluded_applications", self.excluded_applications),
            ("authorized_roots", self.authorized_roots),
        ):
            if not isinstance(values, tuple) or any(not isinstance(value, str) or not value.strip() for value in values):
                raise AssistantSettingsError(f"{name} must contain non-empty strings")
        return replace(
            self,
            excluded_applications=tuple(dict.fromkeys(value.strip().casefold() for value in self.excluded_applications)),
            authorized_roots=tuple(dict.fromkeys(value.strip() for value in self.authorized_roots)),
            speech_language=self.speech_language.strip(),
            quiet_hours_start=_clock(self.quiet_hours_start, "quiet_hours_start"),
            quiet_hours_end=_clock(self.quiet_hours_end, "quiet_hours_end"),
        )

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "AutomationSettings":
        """Build settings from JSON while rejecting unknown or malformed fields."""
        known = set(cls.__dataclass_fields__)
        unknown = set(raw) - known
        if unknown:
            raise AssistantSettingsError(f"Unknown assistant setting(s): {', '.join(sorted(unknown))}")
        values = dict(raw)
        for name in ("excluded_applications", "authorized_roots"):
            if name in values and isinstance(values[name], list):
                values[name] = tuple(values[name])
        return cls(**values).validate()

    def to_mapping(self) -> dict[str, Any]:
        """Return a JSON-safe mapping."""
        values = asdict(self.validate())
        values["excluded_applications"] = list(values["excluded_applications"])
        values["authorized_roots"] = list(values["authorized_roots"])
        return values


def load_assistant_settings(path: str | os.PathLike[str] | Path) -> AutomationSettings:
    """Load settings, returning safe defaults for a missing/invalid file."""
    settings_path = Path(path).expanduser()
    if not settings_path.is_file():
        return AutomationSettings()
    try:
        raw = json.loads(settings_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise AssistantSettingsError("settings document must be an object")
        return AutomationSettings.from_mapping(raw)
    except (OSError, UnicodeError, json.JSONDecodeError, AssistantSettingsError):
        return AutomationSettings()


def save_assistant_settings(
    path: str | os.PathLike[str] | Path,
    settings: AutomationSettings,
) -> AutomationSettings:
    """Validate and atomically persist settings, returning normalized values."""
    normalized = settings.validate()
    destination = Path(path).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
        delete=False,
    )
    temporary = Path(handle.name)
    try:
        with handle:
            json.dump(normalized.to_mapping(), handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return normalized
