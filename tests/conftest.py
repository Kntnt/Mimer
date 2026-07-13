"""Shared fixtures. Every test runs against an isolated store; a guard fixture
fails loudly if any test ever creates the real ``~/.mimer``.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Any

import pytest

from mimer.project import resolve


def needs_embedding_model(items: Iterable[Any]) -> bool:
    """Whether any collected test is marked as needing the embedding model.

    A test is marked ``embedding`` when it embeds — directly via ``embed`` or
    indirectly by driving a hook subprocess that does. The session prefetch keys
    off this so a run that collects no such test never loads the model.
    """

    return any(item.get_closest_marker("embedding") is not None for item in items)


@pytest.fixture(scope="session", autouse=True)
def _prefetch_embedding_model(request: pytest.FixtureRequest) -> None:
    """Fetch the embedding model once, before any embedding-dependent test runs,
    then pin Hugging Face to offline mode for the rest of the session (issue #46).

    The prefetch is gated on collection: it runs only when at least one collected
    test is marked ``embedding``. A targeted run of pure unit tests
    (``pytest tests/test_store_unit.py``, ``pytest -k test_editorconfig``) thus
    never loads the model and stays independent of the network and the model
    cache, even on a cold cache with no connectivity.

    When the suite does include embedding tests, the fetch happens here at session
    start — a single deterministic point rather than lazily inside whichever test
    first calls ``embed`` — so a cache miss fails loudly at one known place, not
    as a flaky mid-suite dependency on Hugging Face being reachable. Subprocesses
    spawned by the hook harness inherit ``HF_HUB_OFFLINE`` and load the same
    cached model without touching the network.
    """

    if not needs_embedding_model(request.session.items):
        return

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


@pytest.fixture
def resolve_project(store_root: Path) -> Callable[[Path], str]:
    """Resolve a cwd to its bound project id, asserting the binding succeeded.

    Replaces the resolve-then-assert helper that was copy-pasted across the suite
    (issue #19). Returns a factory closed over the test's ``store_root`` so a test
    can resolve any cwd — its standard ``project_dir`` or a purpose-built git
    working tree — with one call.
    """

    def _resolve(cwd: Path) -> str:
        resolution = resolve(cwd, root=store_root)
        assert resolution.project_id is not None
        return resolution.project_id

    return _resolve


@pytest.fixture(autouse=True)
def _protect_real_store() -> Iterator[None]:
    """Guarantee no test ever creates or mutates the real ``~/.mimer`` store."""

    real = Path.home() / ".mimer"
    existed = real.exists()
    yield
    if not existed:
        assert not real.exists(), "a test created the real ~/.mimer store"
