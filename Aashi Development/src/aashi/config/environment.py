"""Development / production environment distinction.

The environment is resolved once at startup and then passed explicitly to the
components that need it. It selects which bundled configuration file is loaded
and provides the single answer to "are we running a development build?".
"""

from __future__ import annotations

import os
from enum import StrEnum

from aashi.constants import ENV_VAR_ENVIRONMENT
from aashi.paths import is_frozen

__all__ = ["Environment", "detect_environment"]


class Environment(StrEnum):
    """The environment Aashi is running in.

    ``StrEnum`` members compare equal to their string value, so configuration
    file names and log output can use the member directly.
    """

    DEVELOPMENT = "development"
    PRODUCTION = "production"

    @property
    def is_development(self) -> bool:
        """Return ``True`` for the development environment."""
        return self is Environment.DEVELOPMENT

    @property
    def is_production(self) -> bool:
        """Return ``True`` for the production environment."""
        return self is Environment.PRODUCTION


# Accepted spellings for each environment, so that AASHI_ENV=dev also works.
_ENVIRONMENT_ALIASES: dict[str, Environment] = {
    "development": Environment.DEVELOPMENT,
    "dev": Environment.DEVELOPMENT,
    "debug": Environment.DEVELOPMENT,
    "production": Environment.PRODUCTION,
    "prod": Environment.PRODUCTION,
    "release": Environment.PRODUCTION,
}


def detect_environment(env: dict[str, str] | None = None) -> Environment:
    """Determine the environment for this run.

    Resolution order:

    1. ``AASHI_ENV``, if set to a recognized value.
    2. Frozen/packaged builds default to production.
    3. Runs from source default to development.

    An unrecognized ``AASHI_ENV`` value is ignored rather than fatal: a typo in
    an environment variable must never prevent the application from starting.
    Detection happens before logging is configured, so the fallback is silent by
    design; :func:`aashi.config.settings.load_settings` records the resolved
    environment once logging is available.

    Args:
        env: Environment mapping to read from. Defaults to ``os.environ``.

    Returns:
        The resolved :class:`Environment`.
    """
    environ = os.environ if env is None else env
    raw_value = environ.get(ENV_VAR_ENVIRONMENT, "").strip().lower()
    if raw_value in _ENVIRONMENT_ALIASES:
        return _ENVIRONMENT_ALIASES[raw_value]
    return Environment.PRODUCTION if is_frozen() else Environment.DEVELOPMENT
