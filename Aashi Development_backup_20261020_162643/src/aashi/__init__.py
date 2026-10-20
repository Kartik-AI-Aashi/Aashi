"""Aashi — a modular, local-first, cloud-enhanced personal AI desktop companion.

This package root deliberately contains no imports of submodules. Importing
``aashi`` must stay cheap and must never pull in PySide6, so that non-GUI
consumers (tests, tooling, future headless services) can import the package
without starting Qt.

The version defined here is the single source of truth for the project version;
the build backend reads it directly from this file.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
