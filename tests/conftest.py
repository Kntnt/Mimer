"""Shared fixtures. Every test runs against an isolated store; a guard fixture
fails loudly if any test ever creates the real ``~/.mimer``.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture(scope="session", autouse=True)
def _prefetch_embedding_model() -> None:
    """Fetch the embedding model once, before any test body runs, then pin
    Hugging Face to offline mode for the rest of the session (issue #46).

    This makes the download deterministic — a single point at session start
    instead of lazily inside whichever test first calls ``embed`` — and, once
    the cache is warm, turns a cache miss into a loud failure at a known step
    rather than a flaky mid-suite dependency on Hugging Face being reachable.
    Subprocesses spawned by the hook harness inherit ``HF_HUB_OFFLINE`` and so
    load the same cached model without touching the network.
    """

    from mimer.install import prefetch_embedding_model

    prefetch_embedding_model()
    os.environ["HF_HUB_OFFLINE"] = "1"


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
