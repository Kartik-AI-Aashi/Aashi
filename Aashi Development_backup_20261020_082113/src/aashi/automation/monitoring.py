"""Change-aware, permission-gated proactive screen monitoring.

The monitor is a pull-based coordinator: a host calls :meth:`poll` from a
timer or an event callback.  It does not create a hidden thread or timer.  A
poll first checks the foreground application and policy, then captures at most
one screen when the configured interval has elapsed.  An analyzer is called
only after the application/window or screenshot fingerprint changes.  The
caller decides whether the resulting candidate is rendered visually or spoken
using :class:`ProactiveDecisionEngine`.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Protocol

from .foreground import ForegroundContext, ForegroundProvider
from .models import Action, ActionKind, ActionResult, ActionStatus
from .proactive import (
    CandidateKind,
    ContextEvidence,
    ProactiveCandidate,
    ProactiveContext,
    ProactiveDecision,
    ProactiveDecisionEngine,
)
from .screen import ScreenCapture, ScreenCaptureService

__all__ = [
    "AnalysisKind",
    "MonitoringObservation",
    "MonitoringPolicy",
    "ScreenMonitor",
    "ScreenAnalysis",
]


class AnalysisKind(StrEnum):
    """Meaningful analysis categories emitted by a screen analyzer."""

    NONE = "none"
    ERROR = "error"
    RECOMMENDATION = "recommendation"
    COMPLETION = "completion"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class MonitoringPolicy:
    """Privacy and cost controls for screen monitoring."""

    enabled: bool = False
    interval_seconds: int = 30
    excluded_applications: tuple[str, ...] = ()
    analyze_external: bool = False
    minimum_confidence: float = 0.82
    proactive_speech: bool = False

    def validate(self) -> "MonitoringPolicy":
        if not 5 <= self.interval_seconds <= 3600:
            raise ValueError("Monitoring interval must be between 5 and 3600 seconds")
        if not 0.0 <= self.minimum_confidence <= 1.0:
            raise ValueError("minimum_confidence must be between 0 and 1")
        return MonitoringPolicy(
            enabled=bool(self.enabled),
            interval_seconds=int(self.interval_seconds),
            excluded_applications=tuple(
                dict.fromkeys(value.strip().casefold() for value in self.excluded_applications if value.strip())
            ),
            analyze_external=bool(self.analyze_external),
            minimum_confidence=float(self.minimum_confidence),
            proactive_speech=bool(self.proactive_speech),
        )


@dataclass(frozen=True, slots=True)
class ScreenAnalysis:
    """Structured analyzer output; untrusted screen text never becomes policy."""

    summary: str = ""
    kind: AnalysisKind = AnalysisKind.NONE
    confidence: float = 0.0
    evidence: tuple[str, ...] = ()
    recommendation: str = ""
    sensitive: bool = False


class ScreenAnalyzer(Protocol):
    def __call__(self, context: ForegroundContext, capture: ScreenCapture) -> ScreenAnalysis:
        """Analyze one explicitly permitted screenshot."""


@dataclass(frozen=True, slots=True)
class MonitoringObservation:
    """One monitoring poll outcome."""

    status: ActionStatus
    context: ForegroundContext | None = None
    analysis: ScreenAnalysis | None = None
    decision: ProactiveDecision | None = None
    capture: ScreenCapture | None = None
    message: str = ""


@dataclass(frozen=True, slots=True)
class _Fingerprint:
    application: str
    title: str
    image_digest: str


class ScreenMonitor:
    """Coordinate foreground metadata, capture, analysis, privacy and policy."""

    def __init__(
        self,
        *,
        foreground: ForegroundProvider,
        capture: ScreenCaptureService,
        analyzer: ScreenAnalyzer | None = None,
        decision_engine: ProactiveDecisionEngine | None = None,
        policy: MonitoringPolicy | None = None,
        clock: Callable[[], datetime] | None = None,
        sensitive_application_patterns: Sequence[str] = (
            "bank", "password", "1password", "keepass", "bitwarden", "wallet", "private",
        ),
    ) -> None:
        self._foreground = foreground
        self._capture = capture
        self._analyzer = analyzer
        self._decisions = decision_engine or ProactiveDecisionEngine()
        self._policy = (policy or MonitoringPolicy()).validate()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._last_capture_at: datetime | None = None
        self._last_fingerprint: _Fingerprint | None = None
        self._last_context: ForegroundContext | None = None
        self._sensitive_patterns = tuple(re.compile(pattern, re.IGNORECASE) for pattern in sensitive_application_patterns)

    @property
    def policy(self) -> MonitoringPolicy:
        return self._policy

    @property
    def current_context(self) -> ForegroundContext | None:
        return self._last_context

    def set_policy(self, policy: MonitoringPolicy) -> None:
        self._policy = policy.validate()
        if not self._policy.enabled:
            self.reset()

    def pause(self) -> None:
        """Stop captures immediately while retaining configuration."""
        self._policy = MonitoringPolicy(
            enabled=False,
            interval_seconds=self._policy.interval_seconds,
            excluded_applications=self._policy.excluded_applications,
            analyze_external=self._policy.analyze_external,
            minimum_confidence=self._policy.minimum_confidence,
            proactive_speech=self._policy.proactive_speech,
        )
        self.reset()

    def resume(self) -> None:
        """Resume monitoring explicitly; the next poll may capture once."""
        self._policy = MonitoringPolicy(
            enabled=True,
            interval_seconds=self._policy.interval_seconds,
            excluded_applications=self._policy.excluded_applications,
            analyze_external=self._policy.analyze_external,
            minimum_confidence=self._policy.minimum_confidence,
            proactive_speech=self._policy.proactive_speech,
        )

    def reset(self) -> None:
        self._last_capture_at = None
        self._last_fingerprint = None
        self._last_context = None

    def poll(self, *, force: bool = False) -> MonitoringObservation:
        """Perform one policy-gated observation, never silently uploading pixels."""
        if not self._policy.enabled:
            return MonitoringObservation(ActionStatus.SUPPRESSED, message="Screen monitoring is paused.")
        try:
            context = self._foreground.current()
        except Exception as exc:
            return MonitoringObservation(ActionStatus.ERROR, message=f"Foreground detection failed: {exc}")
        self._last_context = context
        if context is None:
            return MonitoringObservation(ActionStatus.NOT_FOUND, message="No foreground window is available.")
        if self._is_excluded(context):
            return MonitoringObservation(ActionStatus.SUPPRESSED, context=context, message="The foreground application is excluded.")
        now = self._clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        if not force and self._last_capture_at is not None:
            elapsed = (now - self._last_capture_at).total_seconds()
            if elapsed < self._policy.interval_seconds:
                return MonitoringObservation(ActionStatus.SUPPRESSED, context=context, message="Monitoring interval has not elapsed.")

        captured = self._capture.capture()
        if not captured.ok:
            return MonitoringObservation(captured.status, context=context, message=captured.message)
        screen_capture = captured.data
        if not isinstance(screen_capture, ScreenCapture):
            return MonitoringObservation(ActionStatus.ERROR, context=context, message="Capture backend returned an invalid result.")
        self._last_capture_at = now
        fingerprint = _Fingerprint(context.application, context.window_title, _image_digest(screen_capture.image))
        if not force and fingerprint == self._last_fingerprint:
            return MonitoringObservation(ActionStatus.SUPPRESSED, context=context, capture=screen_capture, message="The foreground screen has not changed.")
        self._last_fingerprint = fingerprint
        if self._analyzer is None:
            return MonitoringObservation(
                ActionStatus.SUCCESS,
                context=context,
                capture=screen_capture,
                message="Screen changed, but no analyzer is configured.",
            )
        if not self._policy.analyze_external:
            return MonitoringObservation(
                ActionStatus.SUPPRESSED,
                context=context,
                capture=screen_capture,
                message="Screen changed. External analysis is disabled by privacy settings.",
            )
        if self._is_sensitive_context(context):
            return MonitoringObservation(
                ActionStatus.SUPPRESSED,
                context=context,
                capture=screen_capture,
                message="Sensitive application detected; analysis was not sent.",
            )
        try:
            analysis = self._analyzer(context, screen_capture)
        except Exception as exc:
            return MonitoringObservation(ActionStatus.ERROR, context=context, capture=screen_capture, message=f"Screen analysis failed: {exc}")
        if analysis.sensitive or self._is_sensitive_context(context):
            return MonitoringObservation(ActionStatus.SUPPRESSED, context=context, analysis=analysis, capture=screen_capture, message="Sensitive application detected; analysis was not surfaced.")
        decision = self._decision(context, analysis, now)
        return MonitoringObservation(
            ActionStatus.SUCCESS,
            context=context,
            analysis=analysis,
            decision=decision,
            capture=screen_capture,
            message=analysis.summary,
        )

    def _decision(self, context: ForegroundContext, analysis: ScreenAnalysis, now: datetime) -> ProactiveDecision:
        if analysis.kind is AnalysisKind.NONE or not analysis.recommendation:
            return ProactiveDecision(ActionStatus.SUPPRESSED, reason="No actionable screen evidence.", evaluated_at=now)
        kind = CandidateKind.WARNING if analysis.kind in {AnalysisKind.ERROR, AnalysisKind.WARNING} else CandidateKind.RECOMMENDATION
        candidate = ProactiveCandidate(
            title=f"{kind.value}:{context.application}",
            message=analysis.recommendation,
            score=analysis.confidence,
            kind=kind,
            evidence=tuple(ContextEvidence("screen", item, "vision", analysis.confidence) for item in analysis.evidence)
            + (ContextEvidence("foreground_application", context.application, "foreground", 1.0),),
            dedupe_key=f"{kind.value}:{context.application}:{analysis.recommendation}",
        )
        return self._decisions.decide(ProactiveContext(evidence=candidate.evidence, now=now), (candidate,))

    def _is_excluded(self, context: ForegroundContext) -> bool:
        haystack = f"{context.application} {context.executable or ''}".casefold()
        return any(item in haystack for item in self._policy.excluded_applications)

    def _is_sensitive_context(self, context: ForegroundContext) -> bool:
        haystack = f"{context.application} {context.window_title} {context.executable or ''}"
        return any(pattern.search(haystack) for pattern in self._sensitive_patterns)


def _image_digest(image: Any) -> str:
    """Hash common Qt/PIL/byte-like images without storing their content."""
    if isinstance(image, (bytes, bytearray, memoryview)):
        return hashlib.sha256(bytes(image)).hexdigest()
    for method_name in ("toImage", "tobytes"):
        method = getattr(image, method_name, None)
        if callable(method):
            try:
                converted = method()
                if method_name == "toImage":
                    bits = converted.bits()
                    bits.setsize(converted.sizeInBytes())
                    return hashlib.sha256(bytes(bits)).hexdigest()
                return hashlib.sha256(bytes(converted)).hexdigest()
            except Exception:
                continue
    return hashlib.sha256(repr(image).encode("utf-8", "replace")).hexdigest()
