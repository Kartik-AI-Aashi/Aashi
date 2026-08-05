"""Shared pytest fixtures and configuration for the Aashi test suite.

Two rules apply throughout:

- Tests never touch the real per-user data directory. Anything writable is
  redirected into ``tmp_path``.
- Tests never mutate the real process environment. Functions that read the
  environment accept an injected mapping instead.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from aashi.logging_setup import reset_logging
from aashi.paths import AashiPaths, resolve_paths


def pytest_configure(config: pytest.Config) -> None:
    """Select Qt's offscreen platform when no display is available.

    Windows and macOS always have a display. On Linux CI there may be none, in
    which case Qt must be told explicitly or widget creation aborts the process.
    """
    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def _release_log_handlers() -> Iterator[None]:
    """Close Aashi log handlers after every test.

    Windows refuses to delete a file while a handler holds it open, which would
    make ``tmp_path`` cleanup fail for any test that configures logging.
    """
    yield
    reset_logging()


@pytest.fixture
def isolated_paths(tmp_path: Path) -> AashiPaths:
    """Return :class:`AashiPaths` fully contained inside ``tmp_path``.

    The bundle root points at a temporary directory too, so a test can create
    fake ``assets`` and ``config`` content without touching the repository.
    """
    bundle_root = tmp_path / "bundle"
    (bundle_root / "assets").mkdir(parents=True)
    (bundle_root / "config").mkdir(parents=True)
    return resolve_paths(
        bundle_root=bundle_root,
        user_data_dir=tmp_path / "userdata",
        env={},
    )
