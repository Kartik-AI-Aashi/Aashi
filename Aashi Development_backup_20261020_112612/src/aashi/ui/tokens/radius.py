"""Corner-radius tokens.

Four radii, each with a defined job. The largest is reserved: 20px signals a
floating AI surface, and using it elsewhere weakens that signal.

Nothing here imports Qt.
"""

from __future__ import annotations

from enum import IntEnum

__all__ = ["Radius"]


class Radius(IntEnum):
    """Corner radii, in logical pixels.

    Attributes:
        SMALL: 4px. Badges, tags, inline chips and other small fills.
        MEDIUM: 8px. Buttons, inputs, cards and most surfaces.
        LARGE: 12px. Modals, popovers and other raised containers.
        FLOATING: 20px. Reserved for floating AI surfaces, and nothing else.
    """

    SMALL = 4
    MEDIUM = 8
    LARGE = 12
    FLOATING = 20
