"""Aashi desktop UI.

This package holds everything Qt-facing. Its subpackages exist as boundaries for
future UI modules and are intentionally empty at UI-01:

- ``core`` — UI infrastructure shared by all widgets (base classes, app-level services)
- ``tokens`` — design tokens: colour, typography, spacing, radius, motion
- ``themes`` — theme definitions and the theme engine
- ``components`` — reusable visual components
- ``orb`` — the Aashi Orb
- ``icons`` — icon registry and loading
- ``accessibility`` — accessibility and reduced-motion support
- ``windows`` — top-level windows
- ``overlays`` — overlay and floating surfaces
- ``navigation`` — navigation structure and routing
- ``models`` — models and view-models backing the views
- ``services`` — UI-facing services
- ``utils`` — small UI helpers

Importing this package must not create any Qt object. Widget construction
happens only when a caller instantiates something.
"""

from __future__ import annotations

__all__: list[str] = []
