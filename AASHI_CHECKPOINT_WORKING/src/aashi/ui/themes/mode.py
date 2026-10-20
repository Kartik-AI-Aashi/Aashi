"""Theme mode and colour scheme enumerations.

Two distinct concepts, deliberately kept apart:

- :class:`ThemeMode` is what the *user* chose. It includes ``SYSTEM``, which is
  a deferral rather than an appearance.
- :class:`ColorScheme` is the resolved binary appearance. Every theme satisfies
  exactly one of these, and ``SYSTEM`` always resolves to one of them.

Conflating the two is the usual source of theme bugs: code that stores "dark or
light" loses the user's intent to follow the OS, and code that stores only the
user's choice cannot answer "what colour is the background right now".

Nothing here imports Qt or touches the operating system.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["ColorScheme", "ThemeMode"]


class ColorScheme(StrEnum):
    """A resolved appearance.

    Attributes:
        DARK: Dark surfaces with light text.
        LIGHT: Light surfaces with dark text.
    """

    DARK = "dark"
    LIGHT = "light"


class ThemeMode(StrEnum):
    """The user's theme preference.

    Attributes:
        DARK: Always dark, regardless of the operating system.
        LIGHT: Always light, regardless of the operating system.
        SYSTEM: Follow the operating system's current preference.
    """

    DARK = "dark"
    LIGHT = "light"
    SYSTEM = "system"

    @classmethod
    def parse(cls, value: str) -> ThemeMode:
        """Parse a case-insensitive mode name.

        Args:
            value: ``"dark"``, ``"light"`` or ``"system"``, in any case and with
                surrounding whitespace tolerated.

        Returns:
            The matching mode.

        Raises:
            ValueError: If ``value`` names no known mode. Failing loudly matters
                here: silently falling back to a default would hide a typo in
                the user's settings file.
        """
        try:
            return cls(value.strip().lower())
        except ValueError:
            valid = ", ".join(mode.value for mode in cls)
            raise ValueError(f"Unknown theme mode {value!r}. Expected one of: {valid}") from None

    @property
    def is_fixed(self) -> bool:
        """Whether this mode resolves without consulting the operating system."""
        return self is not ThemeMode.SYSTEM

    def resolve(self, system_scheme: ColorScheme) -> ColorScheme:
        """Resolve this mode to a concrete colour scheme.

        Args:
            system_scheme: The operating system's current preference. Ignored
                unless this mode is :attr:`SYSTEM`.

        Returns:
            The scheme to display.
        """
        if self is ThemeMode.DARK:
            return ColorScheme.DARK
        if self is ThemeMode.LIGHT:
            return ColorScheme.LIGHT
        return system_scheme
