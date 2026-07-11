"""Shared fixtures. Every test runs against an isolated store; a guard fixture
fails loudly if any test ever creates the real ``~/.mimer``.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture
def store_root(tmp_path: Path) -> Path:
    """An isolated store root for one test, never created until a hook runs."""

    return tmp_path / "mimer-store"


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """A throwaway directory standing in for the user's project (a hook's cwd)."""

    project = tmp_path / "project"
    project.mkdir()
    return project


@pytest.fixture(autouse=True)
def _protect_real_store() -> Iterator[None]:
    """Guarantee no test ever creates or mutates the real ``~/.mimer`` store."""

    real = Path.home() / ".mimer"
    existed = real.exists()
    yield
    if not existed:
        assert not real.exists(), "a test created the real ~/.mimer store"
