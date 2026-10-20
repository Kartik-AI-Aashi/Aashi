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
from aashi.config.assistant_settings import (
    AssistantSettingsError,
    AutomationSettings,
    load_assistant_settings,
    save_assistant_settings,
)

__all__ = [
    "ConfigError",
    "AssistantSettingsError",
    "AutomationSettings",
    "Environment",
    "Settings",
    "detect_environment",
    "load_settings",
    "load_assistant_settings",
    "save_assistant_settings",
]
