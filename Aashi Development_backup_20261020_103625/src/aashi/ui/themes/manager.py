"""The runtime theme engine.

:class:`ThemeManager` owns exactly one thing: which appearance is active right
now, and telling everyone when that changes. It holds the user's chosen
:class:`~aashi.ui.themes.mode.ThemeMode`, resolves ``SYSTEM`` against the
operating system, applies the resulting theme to a ``QApplication``, and emits a
signal so open widgets can restyle themselves.

There is deliberately **no module-level instance**. A global theme is the kind of
ambient state that quietly couples every widget to every other one; instead the
manager is created once during application startup and passed explicitly, the
same way :class:`aashi.app.ApplicationContext` is. When the Core service registry
exists it will own the instance, and nothing here will need to change.

Reduced motion lives here too rather than in a second manager: it is the same
kind of value — a user preference that may defer to the operating system, that
widgets must react to, and that is read on every animation.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QGuiApplication

from aashi.ui.accessibility.reduced_motion import MotionPreference
from aashi.ui.themes.definitions import Theme, theme_for
from aashi.ui.themes.mode import ColorScheme, ThemeMode
from aashi.ui.themes.qss import build_base_stylesheet
from aashi.ui.themes.qt_adapters import build_qpalette, to_qfont
from aashi.ui.themes.system import (
    SystemPreferenceReader,
    SystemPreferences,
    read_system_preferences,
)
from aashi.ui.tokens.color import ColorPalette
from aashi.ui.tokens.motion import Duration, MotionRole, resolve_duration
from aashi.ui.tokens.typography import TextRole, style_for

__all__ = ["ThemeManager"]

_logger = logging.getLogger(__name__)


class ThemeManager(QObject):
    """Resolves, applies and broadcasts the active theme.

    Signals:
        theme_changed: Emitted with the new :class:`Theme` whenever the resolved
            appearance changes. Widgets that cache colours reconnect here.
        mode_changed: Emitted with the new :class:`ThemeMode` value whenever the
            user's choice changes, even if the resolved theme happens to stay
            the same — switching from ``dark`` to ``system`` on a dark desktop
            changes intent without changing pixels.
        reduced_motion_changed: Emitted with the new resolved boolean whenever
            the reduced-motion answer changes.
    """

    theme_changed = Signal(object)
    mode_changed = Signal(str)
    reduced_motion_changed = Signal(bool)

    def __init__(
        self,
        *,
        mode: ThemeMode = ThemeMode.SYSTEM,
        motion_preference: MotionPreference = MotionPreference.SYSTEM,
        system_reader: SystemPreferenceReader = read_system_preferences,
        parent: QObject | None = None,
    ) -> None:
        """Create a theme manager.

        Args:
            mode: The initial theme mode. Defaults to following the operating
                system. A future settings module injects the persisted choice
                here; UI-02A does not persist it.
            motion_preference: The initial motion preference.
            system_reader: Callable returning the operating system's appearance
                preferences. Injected by tests so they never depend on the
                machine running them.
            parent: Optional Qt parent.
        """
        super().__init__(parent)
        self._mode = mode
        self._motion_preference = motion_preference
        self._system_reader = system_reader
        self._system = system_reader()
        self._application: QGuiApplication | None = None
        self._style_hints_connected = False
        self._theme = self._resolve_theme()
        self._reduced_motion = self._resolve_reduced_motion()

    # -- state --------------------------------------------------------------

    @property
    def mode(self) -> ThemeMode:
        """The user's chosen mode, which may be :attr:`ThemeMode.SYSTEM`."""
        return self._mode

    @property
    def theme(self) -> Theme:
        """The resolved theme currently in effect."""
        return self._theme

    @property
    def palette(self) -> ColorPalette:
        """The active theme's colour tokens.

        Non-colour tokens do not vary by theme and are imported directly from
        :mod:`aashi.ui.tokens`.
        """
        return self._theme.palette

    @property
    def color_scheme(self) -> ColorScheme:
        """The resolved colour scheme, never :attr:`ThemeMode.SYSTEM`."""
        return self._theme.scheme

    @property
    def system_preferences(self) -> SystemPreferences:
        """The most recent operating-system snapshot this manager read."""
        return self._system

    @property
    def motion_preference(self) -> MotionPreference:
        """The user's chosen motion preference."""
        return self._motion_preference

    @property
    def reduced_motion(self) -> bool:
        """Whether motion should currently be minimised."""
        return self._reduced_motion

    def duration(self, role: MotionRole) -> Duration:
        """Return the duration a ``role`` should animate over right now.

        Widgets call this instead of reading a duration token directly, so that
        the reduced-motion preference is honoured in one place.
        """
        return resolve_duration(role, reduced_motion=self._reduced_motion)

    def stylesheet(self) -> str:
        """Return the application-wide stylesheet for the active theme."""
        return build_base_stylesheet(self._theme)

    # -- mutation -----------------------------------------------------------

    def set_mode(self, mode: ThemeMode) -> None:
        """Change the theme mode and apply the result immediately.

        Args:
            mode: The mode to switch to. Setting the current mode is a no-op.
        """
        if mode is self._mode:
            return
        self._mode = mode
        _logger.info("Theme mode set to %s.", mode.value)
        # Refresh first: a slot handling mode_changed must not observe the old
        # theme still in place.
        self._refresh(reread_system=mode is ThemeMode.SYSTEM)
        self.mode_changed.emit(mode.value)

    def set_motion_preference(self, preference: MotionPreference) -> None:
        """Change the motion preference and notify listeners if the answer moved."""
        if preference is self._motion_preference:
            return
        self._motion_preference = preference
        _logger.info("Motion preference set to %s.", preference.value)
        self._refresh(reread_system=preference is MotionPreference.SYSTEM)

    def refresh_system_preferences(self) -> None:
        """Re-read the operating system's preferences and apply any change.

        Aashi does not continuously observe high-contrast or reduced-motion
        changes; call this when the application regains focus, or from a future
        settings screen. The colour scheme *is* observed continuously when the Qt
        version supports it — see :meth:`attach`.
        """
        self._refresh(reread_system=True)

    # -- application --------------------------------------------------------

    def attach(self, application: QGuiApplication) -> None:
        """Bind this manager to an application and apply the active theme.

        Also subscribes to Qt's colour-scheme change signal where available
        (Qt 6.5 and later), which is what makes ``SYSTEM`` mode follow the
        desktop live rather than only at startup.

        Args:
            application: The running application instance.
        """
        self._application = application
        self._connect_style_hints(application)
        self._apply()

    def _connect_style_hints(self, application: QGuiApplication) -> None:
        """Subscribe to Qt's colour-scheme change signal when it exists."""
        if self._style_hints_connected:
            return
        hints = application.styleHints()
        signal = getattr(hints, "colorSchemeChanged", None)
        if signal is None:
            _logger.debug(
                "This Qt build does not report colour-scheme changes; "
                "SYSTEM mode resolves at startup and on explicit refresh only."
            )
            return
        signal.connect(self._on_system_color_scheme_changed)
        self._style_hints_connected = True

    def _on_system_color_scheme_changed(self, *_: object) -> None:
        """Handle Qt telling us the desktop's colour scheme changed."""
        _logger.debug("Qt reported a system colour-scheme change.")
        self._refresh(reread_system=True)

    def _apply(self) -> None:
        """Push the active theme onto the bound application."""
        application = self._application
        if application is None:
            return
        application.setPalette(build_qpalette(self._theme))
        application.setFont(to_qfont(style_for(TextRole.BODY)))
        set_stylesheet = getattr(application, "setStyleSheet", None)
        if set_stylesheet is not None:
            set_stylesheet(self.stylesheet())
        _logger.debug("Applied the %s theme.", self._theme.name)

    # -- resolution ---------------------------------------------------------

    def _refresh(self, *, reread_system: bool) -> None:
        """Recompute the theme and motion answer, applying and emitting deltas."""
        if reread_system:
            self._system = self._read_system()

        theme = self._resolve_theme()
        theme_moved = theme is not self._theme
        if theme_moved:
            self._theme = theme
            self._apply()

        reduced = self._resolve_reduced_motion()
        motion_moved = reduced != self._reduced_motion
        if motion_moved:
            self._reduced_motion = reduced

        # Emitted after all state has settled, so a slot reading this manager
        # never observes a half-updated object.
        if theme_moved:
            self.theme_changed.emit(theme)
        if motion_moved:
            self.reduced_motion_changed.emit(reduced)

    def _read_system(self) -> SystemPreferences:
        """Read operating-system preferences, preferring Qt's colour scheme.

        Qt's answer is more reliable than the registry — it accounts for the
        platform theme and for per-application overrides — but it only covers
        the colour scheme, so the rest still comes from the injected reader.
        """
        preferences = self._system_reader()
        qt_scheme = self._qt_color_scheme()
        if qt_scheme is not None and qt_scheme is not preferences.color_scheme:
            preferences = SystemPreferences(
                color_scheme=qt_scheme,
                high_contrast=preferences.high_contrast,
                reduced_motion=preferences.reduced_motion,
            )
        return preferences

    def _qt_color_scheme(self) -> ColorScheme | None:
        """Return Qt's view of the desktop colour scheme, if it has one.

        Returns:
            The scheme, or None when the application is not running, the Qt
            version predates ``QStyleHints.colorScheme()``, or Qt reports
            ``Unknown``.
        """
        application = self._application or QGuiApplication.instance()
        if application is None:
            return None
        color_scheme_enum = getattr(Qt, "ColorScheme", None)
        if color_scheme_enum is None:
            return None
        getter = getattr(application.styleHints(), "colorScheme", None)
        if getter is None:
            return None
        value = getter()
        if value == color_scheme_enum.Dark:
            return ColorScheme.DARK
        if value == color_scheme_enum.Light:
            return ColorScheme.LIGHT
        return None

    def _resolve_theme(self) -> Theme:
        """Resolve mode plus system state to a concrete theme."""
        scheme = self._mode.resolve(self._system.color_scheme)
        return theme_for(scheme, high_contrast=self._system.high_contrast)

    def _resolve_reduced_motion(self) -> bool:
        """Resolve the motion preference against the system snapshot."""
        return self._motion_preference.resolve(
            system_reduced=self._system.reduced_motion
        )
