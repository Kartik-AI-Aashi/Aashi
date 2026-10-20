"""Allow the package to be executed with ``python -m aashi``."""

from __future__ import annotations

import sys

from aashi.app import main

if __name__ == "__main__":
    sys.exit(main())
