"""Verify the reduced-motion preference state machine.

Detection itself is OS-dependent and deliberately forgiving, so only the pure
resolution logic is pinned down here; detection gets a shape check.
"""

from __future__ import annotations

import pytest

from aashi.ui.accessibility import MotionPreference
from aashi.ui.accessibility.reduced_motion import detect_system_reduced_motion


def test_parse_accepts_case_variants() -> None:
    assert MotionPreference.parse("full") is MotionPreference.FULL
    assert MotionPreference.parse(" REDUCED ") is MotionPreference.REDUCED


def test_parse_rejects_unknown_preferences() -> None:
    with pytest.raises(ValueError):
        MotionPreference.parse("sometimes")


def test_system_preference_follows_the_os() -> None:
    assert MotionPreference.SYSTEM.resolve(system_reduced=True) is True
    assert MotionPreference.SYSTEM.resolve(system_reduced=False) is False


def test_full_preference_overrides_the_os() -> None:
    assert MotionPreference.FULL.resolve(system_reduced=True) is False


def test_reduced_preference_overrides_the_os() -> None:
    assert MotionPreference.REDUCED.resolve(system_reduced=False) is True


def test_detection_returns_a_bool() -> None:
    assert isinstance(detect_system_reduced_motion(), bool)
