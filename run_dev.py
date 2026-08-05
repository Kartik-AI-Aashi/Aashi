#!/usr/bin/env python
"""Development launcher for Aashi.

Runs Aashi with the development environment forced on, and works without an
editable install by adding ``src`` to the import path when needed.

Use this while developing::

    python run_dev.py

For a normal run — the environment auto-detected — use ``python -m aashi``.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parent / "src"
if _SRC_DIR.is_dir() and str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from aashi.app import run  # noqa: E402  (import must follow the sys.path setup)
from aashi.config import Environment  # noqa: E402

if __name__ == "__main__":
    sys.exit(run(environment=Environment.DEVELOPMENT))
