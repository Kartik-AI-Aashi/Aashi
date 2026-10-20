"""Motion tokens.

Three durations and two easing curves cover every sanctioned animation. The
specification forbids bounce, elastic and overshoot: motion in Aashi explains a
change, it does not decorate one.

Reduced motion is modelled here rather than left to each widget, because "how
much of this animation survives" depends on *what the animation is for*. A
widget declares a :class:`MotionRole` and asks :func:`resolve_duration` for a
number; it never branches on a reduced-motion flag itself. Critically, state
feedback keeps its full duration even under reduced motion — removing it would
hide information rather than calm the interface.

Nothing here imports Qt. :mod:`aashi.ui.themes.qt_adapters` converts an
:class:`Easing` into a ``QEasingCurve`` when a consumer needs one.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, StrEnum
from typing import Final

__all__ = [
    "EASING_ENTRANCE",
    "EASING_EXIT",
    "LOADING_INDICATOR_DELAY_MS",
    "ORB_IDLE_CYCLE_MAX_MS",
    "ORB_IDLE_CYCLE_MIN_MS",
    "ORB_THINKING_CYCLE_MS",
    "TOAST_VISIBLE_MS",
    "TOOLTIP_DELAY_MS",
    "Duration",
    "Easing",
    "MotionRole",
    "resolve_duration",
    "resolve_easing",
]


class Duration(IntEnum):
    """Animation durations, in milliseconds.

    Attributes:
        INSTANT: 0ms. No animation; the change is applied immediately.
        REDUCED: 100ms. Opacity-only crossfade used under reduced motion.
        FAST: 150ms. Hover, press and focus feedback.
        NORMAL: 250ms. Panel and popover transitions.
        SLOW: 400ms. Full-screen and overlay transitions.
    """

    INSTANT = 0
    REDUCED = 100
    FAST = 150
    NORMAL = 250
    SLOW = 400


@dataclass(frozen=True, slots=True)
class Easing:
    """A cubic Bézier easing curve, expressed as its two control points.

    Attributes:
        x1: First control point, x.
        y1: First control point, y.
        x2: Second control point, x.
        y2: Second control point, y.
    """

    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def control_points(self) -> tuple[float, float, float, float]:
        """The four values, in CSS order."""
        return (self.x1, self.y1, self.x2, self.y2)

    @property
    def css(self) -> str:
        """CSS ``cubic-bezier(...)`` notation."""
        return f"cubic-bezier({self.x1:g}, {self.y1:g}, {self.x2:g}, {self.y2:g})"


EASING_ENTRANCE: Final[Easing] = Easing(0.16, 1.0, 0.3, 1.0)
"""Decelerating curve for elements arriving on screen."""

EASING_EXIT: Final[Easing] = Easing(0.4, 0.0, 1.0, 1.0)
"""Accelerating curve for elements leaving the screen."""


class MotionRole(StrEnum):
    """What an animation is *for*, which determines how it degrades.

    Attributes:
        STATE_FEEDBACK: Confirms the interface received input — hover, press,
            focus, toggle. Carries information, so it survives reduced motion.
        TRANSITION: Swaps content in place. Degrades to a short crossfade.
        SPATIAL: Moves, slides or scales something through space. This is what
            triggers vestibular discomfort, so it becomes instant.
        CONTINUOUS: Loops indefinitely — the Orb's idle breathing, shimmer,
            spinners. Becomes static, with the state conveyed another way.
    """

    STATE_FEEDBACK = "state_feedback"
    TRANSITION = "transition"
    SPATIAL = "spatial"
    CONTINUOUS = "continuous"


_FULL_MOTION: Final[dict[MotionRole, Duration]] = {
    MotionRole.STATE_FEEDBACK: Duration.FAST,
    MotionRole.TRANSITION: Duration.NORMAL,
    MotionRole.SPATIAL: Duration.SLOW,
    MotionRole.CONTINUOUS: Duration.SLOW,
}

_REDUCED_MOTION: Final[dict[MotionRole, Duration]] = {
    # Essential feedback is preserved at full speed: without it the user cannot
    # tell whether a control responded.
    MotionRole.STATE_FEEDBACK: Duration.FAST,
    MotionRole.TRANSITION: Duration.REDUCED,
    MotionRole.SPATIAL: Duration.INSTANT,
    MotionRole.CONTINUOUS: Duration.INSTANT,
}


def resolve_duration(role: MotionRole, *, reduced_motion: bool) -> Duration:
    """Return the duration a ``role`` should use.

    Args:
        role: What the animation is for.
        reduced_motion: Whether the reduced-motion preference is active.

    Returns:
        The duration to animate over. :attr:`Duration.INSTANT` means the change
        must be applied without animating at all.
    """
    table = _REDUCED_MOTION if reduced_motion else _FULL_MOTION
    return table[role]


def resolve_easing(role: MotionRole, *, entering: bool) -> Easing:
    """Return the easing curve for a ``role``.

    Args:
        role: What the animation is for. Present for symmetry with
            :func:`resolve_duration` and for future per-role curves.
        entering: True for elements arriving, False for elements leaving.

    Returns:
        The entrance or exit curve.
    """
    del role  # Currently uniform; kept so call sites need not change later.
    return EASING_ENTRANCE if entering else EASING_EXIT


# ---------------------------------------------------------------------------
# Timing that is not an animation duration
# ---------------------------------------------------------------------------

LOADING_INDICATOR_DELAY_MS: Final[int] = 500
"""Work finishing faster than this shows no loading affordance at all.

Flashing a skeleton for 200ms reads as a glitch, not as progress.
"""

TOOLTIP_DELAY_MS: Final[int] = 500
"""Hover dwell time before a tooltip appears."""

TOAST_VISIBLE_MS: Final[int] = 4000
"""How long a toast stays on screen before dismissing itself."""

ORB_IDLE_CYCLE_MIN_MS: Final[int] = 6000
ORB_IDLE_CYCLE_MAX_MS: Final[int] = 8000
"""Range of the Orb's idle breathing cycle. Slow enough to read as alive."""

ORB_THINKING_CYCLE_MS: Final[int] = 1200
"""Period of the Orb's thinking animation."""
