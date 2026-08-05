"""Configuration foundation for Aashi.

Public surface of the configuration layer. Consumers import from this package
rather than from its private modules::

    from aashi.config import Environment, Settings, load_settings

Scope is intentionally narrow — environment detection, startup settings and
logging configuration. The full Aashi settings system, credential storage and
AI configuration are separate, later modules.
"""

from __future__ import annotations

from aashi.config.environment import Environment, detect_environment
from aashi.config.settings import ConfigError, Settings, load_settings

__all__ = [
    "ConfigError",
    "Environment",
    "Settings",
    "detect_environment",
    "load_settings",
]
