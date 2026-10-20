"""Deterministic policy engine for cautious proactive suggestions."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import datetime, time, timezone
from enum import Enum
from typing import Any, Callable

from .models import ActionStatus

__all__ = [
    "CandidateKind",
    "ContextEvidence",
    "ProactiveCandidate",
    "ProactiveContext",
    "ProactiveDecision",
    "ProactiveDecisionEngine",
    "ProactivePolicy",
    "RecommendationCandidate",
    "WarningCandidate",
]


class CandidateKind(str, Enum):
    """The two types of proactive candidate supported by the first core."""

    RECOMMENDATION = "recommendation"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class ContextEvidence:
    """An explainable observation used to produce a candidate."""

    name: str
    value: Any
    source: str = "context"
    confidence: float = 1.0


@dataclass(frozen=True, slots=True)
class ProactiveCandidate:
    """A scored recommendation or warning awaiting policy evaluation."""

    title: str
    message: str
    score: float
    kind: CandidateKind | str = CandidateKind.RECOMMENDATION
    evidence: tuple[ContextEvidence, ...] = ()
    dedupe_key: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        """Stable key used for duplicate suppression."""
        return self.dedupe_key or f"{self.candidate_kind.value}:{self.title}:{self.message}"

    @property
    def candidate_kind(self) -> CandidateKind:
        """Normalize string input to the public enum."""
        try:
            return self.kind if isinstance(self.kind, CandidateKind) else CandidateKind(str(self.kind).lower())
        except ValueError:
            return CandidateKind.RECOMMENDATION


@dataclass(frozen=True, slots=True)
class RecommendationCandidate(ProactiveCandidate):
    """Convenience constructor for a recommendation candidate."""

    kind: CandidateKind | str = CandidateKind.RECOMMENDATION


@dataclass(frozen=True, slots=True)
class WarningCandidate(ProactiveCandidate):
    """Convenience constructor for a warning candidate."""

    kind: CandidateKind | str = CandidateKind.WARNING


@dataclass(frozen=True, slots=True)
class ProactiveContext:
    """Current context and explainable evidence supplied to the engine."""

    evidence: tuple[ContextEvidence, ...] = ()
    now: datetime | None = None


@dataclass(frozen=True, slots=True)
class ProactivePolicy:
    """Thresholds and suppression controls for proactive decisions."""

    recommendation_threshold: float = 0.70
    warning_threshold: float = 0.80
    quiet_hours: tuple[time, time] | None = None
    do_not_disturb: bool = False
    muted: bool = False
    cooldown_seconds: float = 300.0
    duplicate_window_seconds: float = 900.0

    def __post_init__(self) -> None:
        for name in ("recommendation_threshold", "warning_threshold"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        if self.cooldown_seconds < 0 or self.duplicate_window_seconds < 0:
            raise ValueError("suppression windows cannot be negative")


@dataclass(frozen=True, slots=True)
class ProactiveDecision:
    """Explainable output from :class:`ProactiveDecisionEngine`."""

    status: ActionStatus
    candidates: tuple[ProactiveCandidate, ...] = ()
    evidence: tuple[ContextEvidence, ...] = ()
    reason: str = ""
    evaluated_at: datetime | None = None

    @property
    def allowed(self) -> bool:
        """Whether at least one candidate can be shown now."""
        return self.status is ActionStatus.SUCCESS and bool(self.candidates)


Clock = Callable[[], datetime]


class ProactiveDecisionEngine:
    """Apply thresholds, quiet hours, DND, mute and duplicate suppression."""

    def __init__(
        self,
        policy: ProactivePolicy | None = None,
        *,
        recommendation_threshold: float | None = None,
        warning_threshold: float | None = None,
        quiet_hours: tuple[time, time] | None = None,
        do_not_disturb: bool | None = None,
        muted: bool | None = None,
        cooldown_seconds: float | None = None,
        duplicate_window_seconds: float | None = None,
        clock: Clock | None = None,
    ) -> None:
        selected = policy or ProactivePolicy()
        overrides: dict[str, Any] = {}
        for name, value in (
            ("recommendation_threshold", recommendation_threshold),
            ("warning_threshold", warning_threshold),
            ("quiet_hours", quiet_hours),
            ("do_not_disturb", do_not_disturb),
            ("muted", muted),
            ("cooldown_seconds", cooldown_seconds),
            ("duplicate_window_seconds", duplicate_window_seconds),
        ):
            if value is not None:
                overrides[name] = value
        self._policy = replace(selected, **overrides)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._last_emitted_at: datetime | None = None
        self._last_by_key: dict[str, datetime] = {}

    @property
    def policy(self) -> ProactivePolicy:
        """Current immutable policy."""
        return self._policy

    def set_muted(self, muted: bool) -> None:
        """Update the mute gate without changing thresholds."""
        self._policy = ProactivePolicy(
            recommendation_threshold=self._policy.recommendation_threshold,
            warning_threshold=self._policy.warning_threshold,
            quiet_hours=self._policy.quiet_hours,
            do_not_disturb=self._policy.do_not_disturb,
            muted=muted,
            cooldown_seconds=self._policy.cooldown_seconds,
            duplicate_window_seconds=self._policy.duplicate_window_seconds,
        )

    def set_policy(self, policy: ProactivePolicy) -> None:
        """Replace policy after a validated settings change."""
        self._policy = policy

    def set_do_not_disturb(self, enabled: bool) -> None:
        """Update the do-not-disturb gate."""
        self._policy = ProactivePolicy(
            recommendation_threshold=self._policy.recommendation_threshold,
            warning_threshold=self._policy.warning_threshold,
            quiet_hours=self._policy.quiet_hours,
            do_not_disturb=enabled,
            muted=self._policy.muted,
            cooldown_seconds=self._policy.cooldown_seconds,
            duplicate_window_seconds=self._policy.duplicate_window_seconds,
        )

    @staticmethod
    def _in_quiet_hours(current: time, quiet_hours: tuple[time, time] | None) -> bool:
        if quiet_hours is None:
            return False
        start, end = quiet_hours
        if start == end:
            return True
        if start < end:
            return start <= current < end
        return current >= start or current < end

    @staticmethod
    def _elapsed(now: datetime, then: datetime | None) -> float | None:
        if then is None:
            return None
        return max(0.0, (now - then).total_seconds())

    def decide(
        self,
        context_or_candidates: ProactiveContext | Iterable[ProactiveCandidate],
        candidates: Iterable[ProactiveCandidate] | None = None,
    ) -> ProactiveDecision:
        """Evaluate candidates, accepting either ``(context, candidates)`` or
        ``(candidates, context=None)`` for convenient service integration.
        """
        if isinstance(context_or_candidates, ProactiveContext):
            context = context_or_candidates
            candidate_items = tuple(candidates or ())
        else:
            context = ProactiveContext()
            candidate_items = tuple(context_or_candidates)
        now = context.now or self._clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        evidence = tuple(context.evidence)

        if self._policy.muted:
            return ProactiveDecision(ActionStatus.SUPPRESSED, evidence=evidence, reason="Proactive suggestions are muted.", evaluated_at=now)
        if self._policy.do_not_disturb:
            return ProactiveDecision(ActionStatus.SUPPRESSED, evidence=evidence, reason="Do-not-disturb is enabled.", evaluated_at=now)
        if self._in_quiet_hours(now.timetz().replace(tzinfo=None), self._policy.quiet_hours):
            return ProactiveDecision(ActionStatus.SUPPRESSED, evidence=evidence, reason="Quiet hours are active.", evaluated_at=now)
        elapsed_global = self._elapsed(now, self._last_emitted_at)
        if elapsed_global is not None and elapsed_global < self._policy.cooldown_seconds:
            return ProactiveDecision(ActionStatus.SUPPRESSED, evidence=evidence, reason="Proactive cooldown is active.", evaluated_at=now)

        eligible: list[ProactiveCandidate] = []
        suppressed_duplicate = False
        for candidate in candidate_items:
            kind = candidate.candidate_kind
            threshold = self._policy.warning_threshold if kind is CandidateKind.WARNING else self._policy.recommendation_threshold
            if not 0.0 <= candidate.score <= 1.0 or candidate.score < threshold:
                continue
            last_key_time = self._last_by_key.get(candidate.key)
            elapsed_key = self._elapsed(now, last_key_time)
            if elapsed_key is not None and elapsed_key < self._policy.duplicate_window_seconds:
                suppressed_duplicate = True
                continue
            eligible.append(candidate)

        if not eligible:
            reason = "Duplicate candidate suppressed." if suppressed_duplicate else "No candidate met its threshold."
            return ProactiveDecision(ActionStatus.SUPPRESSED, evidence=evidence, reason=reason, evaluated_at=now)

        for candidate in eligible:
            self._last_by_key[candidate.key] = now
        self._last_emitted_at = now
        combined_evidence = evidence + tuple(item for candidate in eligible for item in candidate.evidence)
        return ProactiveDecision(ActionStatus.SUCCESS, tuple(eligible), combined_evidence, "Candidates approved.", now)

    def evaluate(
        self,
        context_or_candidates: ProactiveContext | Iterable[ProactiveCandidate],
        candidates: Iterable[ProactiveCandidate] | None = None,
    ) -> ProactiveDecision:
        """Alias for :meth:`decide`."""
        return self.decide(context_or_candidates, candidates)
