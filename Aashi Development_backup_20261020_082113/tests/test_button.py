"""Verify the UI-02B button component.

The button is the first real component, so it is also the first to be tested
end to end: creation, the three variants, state restyling on theme and motion
changes, and the reduced-motion subscription.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pytestqt", reason="pytest-qt is required for GUI tests")

from PySide6.QtCore import Qt  # noqa: E402

from aashi.ui.accessibility.reduced_motion import MotionPreference  # noqa: E402
from aashi.ui.components.button import AashiButton, ButtonVariant  # noqa: E402
from aashi.ui.themes.definitions import DARK_THEME, LIGHT_THEME  # noqa: E402
from aashi.ui.themes.manager import ThemeManager  # noqa: E402
from aashi.ui.themes.mode import ColorScheme, ThemeMode  # noqa: E402
from aashi.ui.themes.system import SystemPreferences  # noqa: E402


def _manager() -> ThemeManager:
    return ThemeManager(system_reader=lambda: SystemPreferences(
        color_scheme=ColorScheme.DARK,
        high_contrast=False,
        reduced_motion=False,
    ))


@pytest.mark.parametrize("variant", list(ButtonVariant))
def test_button_builds_for_every_variant(qtbot, variant: ButtonVariant) -> None:
    button = AashiButton("Action", _manager(), variant=variant)
    qtbot.addWidget(button)

    assert button.variant is variant
    assert button.text() == "Action"
    assert button.styleSheet()


def test_primary_uses_the_theme_accent(qtbot) -> None:
    button = AashiButton("Save", _manager(), variant=ButtonVariant.PRIMARY)
    qtbot.addWidget(button)

    stylesheet = button.styleSheet()
    assert DARK_THEME.palette.accent.base.css in stylesheet
    assert DARK_THEME.palette.accent.on_accent.css in stylesheet
    assert "background-color: transparent" not in stylesheet


def test_secondary_and_ghost_use_their_sanctioned_fills(qtbot) -> None:
    secondary = AashiButton("Cancel", _manager(), variant=ButtonVariant.SECONDARY)
    qtbot.addWidget(secondary)
    assert DARK_THEME.palette.surface.primary.css in secondary.styleSheet()

    ghost = AashiButton("More", _manager(), variant=ButtonVariant.GHOST)
    qtbot.addWidget(ghost)
    assert DARK_THEME.palette.accent.tint_hover.css in ghost.styleSheet()
    assert DARK_THEME.palette.text.primary.css in ghost.styleSheet()


def test_set_variant_rebuilds_the_stylesheet(qtbot) -> None:
    button = AashiButton("Save", _manager(), variant=ButtonVariant.PRIMARY)
    qtbot.addWidget(button)

    button.set_variant(ButtonVariant.GHOST)

    assert button.variant is ButtonVariant.GHOST
    assert DARK_THEME.palette.text.primary.css in button.styleSheet()


def test_button_restyles_when_the_theme_changes(qtbot) -> None:
    manager = _manager()
    button = AashiButton("Save", manager, variant=ButtonVariant.PRIMARY)
    qtbot.addWidget(button)
    assert DARK_THEME.palette.accent.base.css in button.styleSheet()

    manager.set_mode(ThemeMode.LIGHT)

    assert LIGHT_THEME.palette.accent.base.css in button.styleSheet()


def test_button_restyles_on_reduced_motion_change(qtbot, monkeypatch) -> None:
    manager = _manager()
    calls: list[int] = []
    monkeypatch.setattr(AashiButton, "_restyle", lambda self, *_: calls.append(1))
    button = AashiButton("Save", manager)
    qtbot.addWidget(button)
    calls.clear()

    manager.set_motion_preference(MotionPreference.REDUCED)

    assert calls  # the button re-styled itself on the motion change
    assert manager.reduced_motion is True


def test_button_survives_motion_preference_changes(qtbot) -> None:
    manager = _manager()
    button = AashiButton("Save", manager)
    qtbot.addWidget(button)

    manager.set_motion_preference(MotionPreference.REDUCED)

    assert manager.reduced_motion is True
    assert button.styleSheet()


def test_high_contrast_theme_adds_a_permanent_outline(qtbot) -> None:
    manager = ThemeManager(system_reader=lambda: SystemPreferences(
        color_scheme=ColorScheme.DARK,
        high_contrast=True,
        reduced_motion=False,
    ))
    button = AashiButton("Save", manager, variant=ButtonVariant.GHOST)
    qtbot.addWidget(button)

    assert manager.theme.high_contrast
    assert manager.theme.palette.border.strong.css in button.styleSheet()


def test_disabled_button_does_not_emit_clicked(qtbot) -> None:
    button = AashiButton("Save", _manager())
    qtbot.addWidget(button)
    button.setEnabled(False)

    with qtbot.assertNotEmitted(button.clicked):
        qtbot.mouseClick(button, Qt.MouseButton.LeftButton)
