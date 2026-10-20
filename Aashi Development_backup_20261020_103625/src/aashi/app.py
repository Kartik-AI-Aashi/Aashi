"""Application bootstrap and entry point for Aashi.

Startup sequence:

1. Resolve filesystem locations (:mod:`aashi.paths`).
2. Resolve settings for the active environment (:mod:`aashi.config`).
3. Create per-user writable directories.
4. Configure logging.
5. Create and configure the ``QApplication``.
6. Create the theme manager and apply the active theme.
7. Show the top-level window and run the Qt event loop.

Steps 1-4 are Qt-free and exposed as :func:`create_context`, so tests and future
headless subsystems can build an application context without starting Qt.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from PySide6.QtWidgets import QApplication

from aashi.config import ConfigError, Environment, Settings, load_settings
from aashi.constants import (
    APP_NAME,
    APP_VERSION,
    BOOTSTRAP_WINDOW_MIN_HEIGHT,
    BOOTSTRAP_WINDOW_MIN_WIDTH,
    EXIT_CONFIG_ERROR,
    ORGANIZATION_DOMAIN,
    ORGANIZATION_NAME,
)
from aashi.logging_setup import configure_logging, get_logger
from aashi.paths import AashiPaths, resolve_paths

__all__ = ["ApplicationContext", "create_application", "create_context", "main", "run"]

_logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ApplicationContext:
    """Everything resolved before Qt starts.

    Passed explicitly to the components that need it rather than exposed as
    global state, so that future modules and tests can supply their own context.
    """

    settings: Settings
    paths: AashiPaths

    @property
    def environment(self) -> Environment:
        """The active environment."""
        return self.settings.environment


def create_context(environment: Environment | None = None) -> ApplicationContext:
    """Resolve paths, settings, writable directories and logging.

    Args:
        environment: Forces a specific environment. When omitted the
            environment is auto-detected.

    Returns:
        The fully initialized :class:`ApplicationContext`.

    Raises:
        ConfigError: If configuration exists but is invalid.
    """
    paths = resolve_paths()
    settings = load_settings(environment=environment, config_dir=paths.bundled_config_dir)
    paths.ensure_user_directories()
    configure_logging(settings, log_file=paths.log_file)

    _logger.info("%s %s starting in %s mode.", APP_NAME, APP_VERSION, settings.environment)
    _logger.debug("Bundle root: %s", paths.bundle_root)
    _logger.debug("User data directory: %s", paths.user_data_dir)
    return ApplicationContext(settings=settings, paths=paths)


def create_application(argv: list[str] | None = None) -> QApplication:
    """Return a configured ``QApplication``.

    Reuses an existing instance when one is already running — Qt permits only
    one per process, and test fixtures create theirs first.

    Args:
        argv: Argument vector handed to Qt. Defaults to ``sys.argv``.
    """
    application = QApplication.instance()
    if application is None:
        application = QApplication(sys.argv if argv is None else argv)

    application.setApplicationName(APP_NAME)
    application.setApplicationDisplayName(APP_NAME)
    application.setApplicationVersion(APP_VERSION)
    application.setOrganizationName(ORGANIZATION_NAME)
    application.setOrganizationDomain(ORGANIZATION_DOMAIN)
    return application


def run(argv: list[str] | None = None, environment: Environment | None = None) -> int:
    """Start Aashi and run the Qt event loop until the application exits.

    Args:
        argv: Argument vector handed to Qt. Defaults to ``sys.argv``.
        environment: Forces a specific environment; normally auto-detected.

    Returns:
        The process exit code.
    """
    try:
        context = create_context(environment=environment)
    except ConfigError as exc:
        # Logging is not configured yet at this point, so report on stderr.
        print(f"{APP_NAME}: configuration error: {exc}", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    if sys.platform == "win32" and os.environ.get("QT_QPA_PLATFORM") != "offscreen":
        try:
            import ctypes

            user32 = ctypes.windll.user32
            hdesk = user32.OpenDesktopW("Default", 0, False, 0x01FF)
            if hdesk:
                user32.SetThreadDesktop(hdesk)
        except Exception:
            pass

    application = create_application(argv)

    # UI-02A: the theme manager is created once here and passed explicitly. It
    # is deliberately not a module-level singleton; when the Core service
    # registry exists it will own this instance instead.
    from aashi.ui.themes.manager import ThemeManager

    theme_manager = ThemeManager(parent=application)
    theme_manager.attach(application)

    from aashi.ui.windows.chat_window import AashiChatWindow
    from aashi.ui.windows.desktop_shell import AashiDesktopWindow

    chat_window = AashiChatWindow(theme_manager)
    chat_window.setMinimumSize(BOOTSTRAP_WINDOW_MIN_WIDTH, BOOTSTRAP_WINDOW_MIN_HEIGHT)
    window = AashiDesktopWindow(chat_window)
    window.setWindowTitle(APP_NAME)
    window.setMinimumSize(BOOTSTRAP_WINDOW_MIN_WIDTH, BOOTSTRAP_WINDOW_MIN_HEIGHT)
    window.resize(1020, 720)

    # Keep one source of truth for desktop state while allowing both the main
    # surface and the tray to control the same existing conversation window.
    chat_window.task_status_changed.connect(window.set_task_status)
    chat_window.talking_mode_changed.connect(window.set_talking_mode)
    chat_window.screen_monitoring_changed.connect(window.set_screen_monitoring)
    window.talking_mode_changed.connect(chat_window.set_talking_mode)
    window.screen_monitoring_changed.connect(chat_window.set_screen_monitoring)
    window.set_talking_mode(chat_window.talking_mode)
    window.set_screen_monitoring(chat_window.screen_monitoring)
    window.set_task_status(chat_window.task_status)
    window.show()
    window.raise_()
    window.activateWindow()

    if sys.platform == "win32" and os.environ.get("QT_QPA_PLATFORM") != "offscreen":
        try:
            import ctypes

            ctypes.windll.user32.SetForegroundWindow(int(window.winId()))
        except Exception:
            pass

    _logger.debug("Entering Qt event loop.")
    exit_code = application.exec()
    _logger.info("%s exiting with code %d.", APP_NAME, exit_code)
    return exit_code


def main(argv: list[str] | None = None) -> int:
    """Console/GUI script entry point.

    Returns:
        The process exit code, for ``sys.exit``.
    """
    return run(argv)


if __name__ == "__main__":
    sys.exit(main())
