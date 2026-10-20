"""Foreground-window context providers.

The provider is intentionally small and injectable.  The Windows adapter uses
only Win32 metadata calls and does not capture pixels or read window contents.
On unsupported hosts it returns no context, allowing the rest of Aashi to keep
working without pretending to know which application is active.
"""

from __future__ import annotations

import ctypes
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

__all__ = [
    "ForegroundContext",
    "ForegroundProvider",
    "NullForegroundProvider",
    "WindowsForegroundProvider",
]


@dataclass(frozen=True, slots=True)
class ForegroundContext:
    """Safe metadata about the active window, without its content."""

    application: str
    window_title: str
    process_id: int | None = None
    executable: str | None = None
    captured_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ForegroundProvider(Protocol):
    """Port for retrieving the current foreground application metadata."""

    def current(self) -> ForegroundContext | None:
        """Return current metadata or ``None`` when unavailable."""


class NullForegroundProvider:
    """Safe provider for unsupported hosts or disabled monitoring."""

    def current(self) -> ForegroundContext | None:
        return None


class WindowsForegroundProvider:
    """Windows foreground provider using lazy ``user32``/``kernel32`` calls."""

    def __init__(self, *, process_name: Callable[[int], str | None] | None = None) -> None:
        if os.name != "nt":
            raise RuntimeError("WindowsForegroundProvider requires Windows")
        self._user32 = ctypes.windll.user32
        self._kernel32 = ctypes.windll.kernel32
        self._process_name = process_name or self._default_process_name

    def current(self) -> ForegroundContext | None:
        hwnd = self._user32.GetForegroundWindow()
        if not hwnd:
            return None
        process_id = ctypes.c_ulong()
        self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        title_length = self._user32.GetWindowTextLengthW(hwnd)
        title_buffer = ctypes.create_unicode_buffer(max(title_length + 1, 1))
        self._user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))
        executable = self._process_name(int(process_id.value))
        application = os.path.basename(executable) if executable else "Unknown application"
        return ForegroundContext(
            application=application,
            window_title=title_buffer.value,
            process_id=int(process_id.value),
            executable=executable,
            captured_at=datetime.now(timezone.utc),
        )

    def _default_process_name(self, process_id: int) -> str | None:
        # PROCESS_QUERY_LIMITED_INFORMATION is sufficient for the executable
        # name and avoids opening a handle with write/debug privileges.
        handle = self._kernel32.OpenProcess(0x1000, False, process_id)
        if not handle:
            return None
        try:
            buffer = ctypes.create_unicode_buffer(1024)
            size = ctypes.c_ulong(len(buffer))
            if self._kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                return buffer.value
            return None
        finally:
            self._kernel32.CloseHandle(handle)
