"""Accessibility support.

Reserved for accessible naming, keyboard navigation, focus handling, contrast
support and reduced-motion behaviour.

UI-02A implements only the reduced-motion foundation
(:mod:`~aashi.ui.accessibility.reduced_motion`): detecting the operating
system's animation preference and resolving it against an explicit override. The
rest of the accessibility subsystem belongs to a later module; this package is
still mostly a boundary.

Nothing in this package imports Qt.
"""

from __future__ import annotations

from aashi.ui.accessibility.reduced_motion import (
    MotionPreference,
    detect_system_reduced_motion,
)

__all__ = ["MotionPreference", "detect_system_reduced_motion"]
