"""Shared pytest fixtures and configuration for the Aashi test suite.

Two rules apply throughout:

- Tests never touch the real per-user data directory. Anything writable is
  redirected into ``tmp_path``.
- Tests never mutate the real process environment. Functions that read the
  environment accept an injected mapping instead.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from aashi.logging_setup import reset_logging
from aashi.paths import AashiPaths, resolve_paths


def pytest_configure(config: pytest.Config) -> None:
    """Run the GUI suite on Qt's offscreen platform for deterministic geometry.

    Widget pixel geometry is not reproducible on a real display: under DPI
    scaling the Windows platform reports a different QLabel word-wrap sizeHint
    than the offscreen backend (e.g. 450 px vs 948 px for the same text), which
    shifts layout-derived widths and makes pixel assertions flaky. Headless
    Linux additionally has no display at all. Forcing offscreen makes the whole
    suite stable on every host; a developer can still opt into a real window by
    setting ``QT_QPA_PLATFORM`` explicitly.
    """
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
