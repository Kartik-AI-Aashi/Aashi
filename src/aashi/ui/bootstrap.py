"""TEMPORARY foundation window for UI-01.

This window is scaffolding, not design. It exists only to prove that Python
starts, PySide6 loads, ``QApplication`` initializes, the package imports
correctly and the Qt event loop runs.

It deliberately applies no styling: no colours, no fonts, no spacing values.
Those belong to the design-token and theme modules. A later UI module deletes
this file and replaces it with the real Aashi window.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from aashi.constants import (
    APP_VERSION,
    BOOTSTRAP_WINDOW_MIN_HEIGHT,
    BOOTSTRAP_WINDOW_MIN_WIDTH,
    BOOTSTRAP_WINDOW_TEXT,
    BOOTSTRAP_WINDOW_TITLE,
)

__all__ = ["FoundationWindow"]


class FoundationWindow(QWidget):
    """Minimal window confirming that the Aashi UI foundation works.

    Args:
        environment_name: Active environment, shown so a developer can tell at
            a glance which configuration the run picked up.
        parent: Optional Qt parent.
    """

    def __init__(self, environment_name: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.setObjectName("aashiFoundationWindow")
        self.setWindowTitle(BOOTSTRAP_WINDOW_TITLE)
        self.setMinimumSize(BOOTSTRAP_WINDOW_MIN_WIDTH, BOOTSTRAP_WINDOW_MIN_HEIGHT)

        self._heading = QLabel(BOOTSTRAP_WINDOW_TEXT, self)
        self._heading.setObjectName("aashiFoundationHeading")
        self._heading.setAlignment(Qt.AlignmentFlag.AlignCenter)

        details = f"v{APP_VERSION}"
        if environment_name:
            details = f"{details} — {environment_name}"
        self._details = QLabel(details, self)
        self._details.setObjectName("aashiFoundationDetails")
        self._details.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout = QVBoxLayout(self)
        layout.addStretch(1)
        layout.addWidget(self._heading)
        layout.addWidget(self._details)
        layout.addStretch(1)

    @property
    def heading_text(self) -> str:
        """The primary label's text. Exposed for the foundation smoke test."""
        return self._heading.text()
