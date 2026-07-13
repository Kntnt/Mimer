"""Store-wide locks are named by the module that owns their artefact (#50).

The registry's read-modify-write and the permanent bundle's mutations each take a
store-wide lock. #50 routes those through their owners — ``registry_lock()`` for
the registry, ``named_lock("bundle")`` for the bundle — and deletes the fabricated
project-id sentinels (``REGISTRY_LOCK``, ``_BUNDLE_LOCK``) that used to reach the
same lock files by passing a dunder id to ``project_lock``. These tests pin the new
interface and prove, behaviourally, that it locks exactly what the sentinels did —
the same on-disk lock files, so the rewrite is behaviour-preserving.
"""

from __future__ import annotations

import threading
from pathlib import Path

from mimer import bundle, project, registry
from mimer.store import ensure_store
from mimer.storeio import named_lock

# The four tokens #50 deletes: two fabricated sentinel ids and the two dunder
# lock-name literals they expanded to on disk.
_FORBIDDEN_TOKENS = ("__registry__", "__bundle__", "REGISTRY_LOCK", "_BUNDLE_LOCK")


def test_registry_module_exposes_registry_lock(store_root: Path) -> None:
    """The registry module owns the registry lock and exposes it as
    ``registry_lock()``; holding it creates the store-wide ``__registry__`` lock
    file, proving it delegates to ``named_lock("registry")`` and keeps the on-disk
    name unchanged."""

    ensure_store(store_root)

    with registry.registry_lock(root=store_root):
        assert (store_root / "locks" / "__registry__.lock").exists()


def test_registry_lock_is_the_named_registry_lock(store_root: Path) -> None:
    """``registry_lock()`` is exactly ``named_lock("registry")`` — the store-wide
    lock the ``REGISTRY_LOCK`` sentinel reached — so a holder excludes a concurrent
    ``named_lock("registry")`` taken in another thread."""

    ensure_store(store_root)
    acquired = threading.Event()

    # A worker races for the same lock under its named spelling while the main
    # thread holds it through registry_lock().
    def take_named() -> None:
        with named_lock("registry", root=store_root):
            acquired.set()

    with registry.registry_lock(root=store_root):
        worker = threading.Thread(target=take_named, daemon=True)
        worker.start()
        assert not acquired.wait(0.5), "named_lock('registry') did not block on a held registry_lock()"

    # Released, the worker acquires the very same lock and finishes.
    assert acquired.wait(2), "named_lock('registry') never acquired the lock after release"
    worker.join(2)


def test_bundle_write_contends_on_the_named_bundle_lock(store_root: Path) -> None:
    """A bundle mutation serialises on ``named_lock("bundle")`` — the store-wide
    lock that owns the permanent bundle. Holding that named lock blocks a concurrent
    ``create_concept`` until release, proving the bundle routes its internal locking
    through the named lock rather than a fabricated project id."""

    ensure_store(store_root)
    created = threading.Event()

    def create() -> None:
        bundle.create_concept(
            title="Deploy on Fridays",
            body="Releases go out on Fridays after standup.",
            concept_type="Decision",
            origin="proj-b",
            root=store_root,
        )
        created.set()

    with named_lock("bundle", root=store_root):
        worker = threading.Thread(target=create, daemon=True)
        worker.start()
        assert not created.wait(0.5), "create_concept did not contend on named_lock('bundle')"

    # Released, the bundle write acquires the same lock and completes.
    assert created.wait(2), "create_concept never acquired the bundle lock after release"
    worker.join(2)


def test_registry_lock_sentinel_is_deleted() -> None:
    """The ``REGISTRY_LOCK`` sentinel is gone from the project module: its lock now
    lives on the registry module as ``registry_lock()``."""

    assert not hasattr(project, "REGISTRY_LOCK")


def test_bundle_lock_sentinel_is_deleted() -> None:
    """The ``_BUNDLE_LOCK`` sentinel is gone from the bundle module: the bundle
    locks through ``named_lock("bundle")`` directly."""

    assert not hasattr(bundle, "_BUNDLE_LOCK")


def test_no_sentinel_or_dunder_lock_ids_remain_in_source() -> None:
    """No production module still spells a fabricated sentinel id or the dunder
    lock-name literal it expanded to (#50 acceptance grep). The on-disk lock files
    keep their dunder names, but those are built by storeio's ``__<name>__``
    template, never written as a literal."""

    src = Path(__file__).resolve().parent.parent / "src" / "mimer"
    offenders = [
        f"{path.relative_to(src)}: {token}"
        for path in sorted(src.rglob("*.py"))
        for token in _FORBIDDEN_TOKENS
        if token in path.read_text(encoding="utf-8")
    ]
    assert not offenders, f"forbidden sentinel/dunder lock ids remain: {offenders}"
