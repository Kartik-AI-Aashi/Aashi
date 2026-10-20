"""On-demand screen capture abstractions.

No timer, polling loop, or background capture is created here.  A caller asks
for one screen or all current screens, and the injected backend performs that
single capture.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from .models import Action, ActionKind, ActionResult, ActionStatus

__all__ = [
    "QScreenBackend",
    "ScreenCapture",
    "ScreenCaptureBackend",
    "ScreenCaptureService",
    "ScreenInfo",
]


@dataclass(frozen=True, slots=True)
class ScreenInfo:
    """Stable metadata for one display."""

    index: int
    name: str
    geometry: tuple[int, int, int, int] | None = None


@dataclass(frozen=True, slots=True)
class ScreenCapture:
    """One on-demand image returned by a backend."""

    screen: ScreenInfo
    image: Any
    captured_at: datetime


class ScreenCaptureBackend(Protocol):
    """Minimal backend protocol used by :class:`ScreenCaptureService`."""

    def screens(self) -> Sequence[Any]:
        """Return the currently available screen handles."""

    def capture(self, screen: Any) -> Any:
        """Capture one supplied screen handle now."""


def _screen_name(screen: Any, index: int) -> str:
    name = getattr(screen, "name", None)
    if callable(name):
        name = name()
    return str(name) if name else f"Screen {index + 1}"


def _screen_geometry(screen: Any) -> tuple[int, int, int, int] | None:
    geometry = getattr(screen, "geometry", None)
    if callable(geometry):
        geometry = geometry()
    if geometry is None:
        return None
    values: list[int] = []
    for attribute in ("x", "y", "width", "height"):
        value = getattr(geometry, attribute, None)
        value = value() if callable(value) else value
        if value is None:
            return None
        values.append(int(value))
    return tuple(values)  # type: ignore[return-value]


class QScreenBackend:
    """PySide6 ``QScreen`` adapter with a lazy, optional Qt dependency.

    Pass ``screen_provider`` in tests or another host integration.  When it is
    omitted, PySide6 is imported only while constructing this backend.  The
    core package itself remains importable without Qt.
    """

    def __init__(self, screen_provider: Callable[[], Sequence[Any]] | None = None) -> None:
        if screen_provider is None:
            try:
                from PySide6.QtGui import QGuiApplication
            except ImportError as exc:  # pragma: no cover - depends on install
                raise RuntimeError("QScreenBackend requires the existing PySide6 installation") from exc
            screen_provider = QGuiApplication.screens
        self._screen_provider = screen_provider

    def screens(self) -> Sequence[Any]:
        """Return all screens currently reported by Qt."""
        return tuple(self._screen_provider())

    def capture(self, screen: Any) -> Any:
        """Grab one screen's current pixels; no continuous capture is used."""
        grab = getattr(screen, "grabWindow", None)
        if not callable(grab):
            raise TypeError("The supplied object is not a QScreen-like handle")
        return grab(0)


class ScreenCaptureService:
    """List displays and capture one or all displays on demand."""

    def __init__(self, backend: ScreenCaptureBackend) -> None:
        self._backend = backend

    def list_screens(self) -> tuple[ScreenInfo, ...]:
        """Return metadata for every screen currently available."""
        return tuple(ScreenInfo(index, _screen_name(screen, index), _screen_geometry(screen)) for index, screen in enumerate(self._backend.screens()))

    def capture(self, screen_index: int = 0) -> ActionResult:
        """Capture one screen immediately."""
        action = Action(ActionKind.CAPTURE_SCREEN, parameters={"screen_index": screen_index})
        if not isinstance(screen_index, int) or isinstance(screen_index, bool) or screen_index < 0:
            return ActionResult.failure(ActionStatus.INVALID, "screen_index must be a non-negative integer", action=action)
        try:
            screens = tuple(self._backend.screens())
        except Exception as exc:
            return ActionResult.failure(
                ActionStatus.ERROR,
                f"Could not enumerate screens: {exc}",
                action=action,
                error=str(exc),
            )
        if screen_index >= len(screens):
            return ActionResult.failure(ActionStatus.NOT_FOUND, "The requested screen does not exist.", action=action)
        try:
            screen = screens[screen_index]
            info = ScreenInfo(screen_index, _screen_name(screen, screen_index), _screen_geometry(screen))
            image = self._backend.capture(screen)
        except Exception as exc:
            return ActionResult.failure(ActionStatus.ERROR, f"Could not capture screen: {exc}", action=action, error=str(exc))
        return ActionResult.success(
            ScreenCapture(info, image, datetime.now(timezone.utc)),
            message="Screen captured on demand.",
            action=action,
        )

    def capture_all(self) -> tuple[ActionResult, ...]:
        """Capture each currently available screen once, in display order."""
        try:
            screens = tuple(self._backend.screens())
        except Exception as exc:
            return (
                ActionResult.failure(
                    ActionStatus.ERROR,
                    f"Could not enumerate screens: {exc}",
                    action=Action(ActionKind.CAPTURE_SCREEN),
                    error=str(exc),
                ),
            )
        results: list[ActionResult] = []
        for index, screen in enumerate(screens):
            action = Action(ActionKind.CAPTURE_SCREEN, parameters={"screen_index": index})
            try:
                info = ScreenInfo(index, _screen_name(screen, index), _screen_geometry(screen))
                image = self._backend.capture(screen)
            except Exception as exc:
                results.append(
                    ActionResult.failure(
                        ActionStatus.ERROR,
                        f"Could not capture screen: {exc}",
                        action=action,
                        error=str(exc),
                    )
                )
            else:
                results.append(
                    ActionResult.success(
                        ScreenCapture(info, image, datetime.now(timezone.utc)),
                        message="Screen captured on demand.",
                        action=action,
                    )
                )
        return tuple(results)
