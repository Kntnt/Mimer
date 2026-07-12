"""Owner-only permission invariant (ADR 0013, issue #26).

The store concentrates every project's memory in one place, so every file and
directory Mimer creates must be owner-only on its own — not merely because the
0700 root happens to mask it. The index (``index.db``) is the single most
concentrated copy of all projects' memory text; its WAL/SHM sidecars carry the
same content. These tests pin the paths that historically drifted: the index
database and its sidecars (0600), the project subdirectories created as
intermediates of a deeper write (0700), the uninstall pointer and a recreated
failure log (0600), and the heal sweep that re-pins a tree an older install left
loose.

Every test runs under a deliberately permissive umask (see ``_permissive_umask``)
so an un-chmod'd default lands world-readable and the assertions genuinely
discriminate — otherwise a restrictive-umask runner would already yield 0600/0700
with no fix in place and let a regression pass unnoticed.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Iterator
from pathlib import Path

import pytest

from mimer import db
from mimer.failure_log import log_failure
from mimer.index import index_db_path
from mimer.install import write_uninstall_pointer
from mimer.longterm import append_entry
from mimer.paths import LOG_FILENAME
from mimer.store import ensure_store, heal_permissions
from mimer.storeio import write_atomic


@pytest.fixture(autouse=True)
def _permissive_umask() -> Iterator[None]:
    """Force a permissive umask so an un-chmod'd file lands world-readable.

    The assertions below pin exact modes; without a known-loose umask, whether a
    reverted fix is caught depends on the runner's ambient umask — under a
    restrictive 0o077 the default is already 0600/0700 and a regression slips
    through. Pinning 0o022 makes the default loose (0755 dirs, 0644 files), so the
    explicit chmods are exactly what the tests observe.
    """

    previous = os.umask(0o022)
    try:
        yield
    finally:
        os.umask(previous)


def test_index_db_and_sidecars_are_owner_only(store_root: Path) -> None:
    """``index.db`` and its live WAL/SHM sidecars end up with mode 0600."""

    ensure_store(store_root)
    path = index_db_path(store_root)

    # Open the index and force a write so SQLite materialises the WAL and SHM
    # sidecars; assert while the connection is open, since a clean close
    # checkpoints and deletes them.
    connection = db.connect(path)
    try:
        connection.execute("CREATE TABLE t (x)")
        connection.execute("INSERT INTO t VALUES (1)")
        # Assert the sidecars before index.db: they are the half of the invariant
        # a regression could drop silently, so the check must reach them instead
        # of short-circuiting on the main file.
        for suffix in ("-wal", "-shm", ""):
            sidecar = path.with_name(path.name + suffix)
            assert sidecar.exists(), f"expected {suffix or 'index.db'} to exist"
            assert stat.S_IMODE(sidecar.stat().st_mode) == 0o600, suffix or "index.db"
    finally:
        connection.close()


def test_connect_repins_loose_sidecars_from_a_prior_session(store_root: Path) -> None:
    """``connect`` re-pins a WAL/SHM sidecar a prior session left at a looser mode.

    This exercises the correction loop specifically — the mechanism distinct from
    SQLite inheriting the main file's mode when it first creates a sidecar. A
    first connection materialises real sidecars; they are loosened to stand in for
    a prior session, and reopening must heal them.
    """

    ensure_store(store_root)
    path = index_db_path(store_root)

    # Materialise real WAL/SHM sidecars via a first connection, then loosen them
    # so only the correction loop of a later connection can restore 0600.
    first = db.connect(path)
    first.execute("CREATE TABLE t (x)")
    first.execute("INSERT INTO t VALUES (1)")
    for suffix in ("-wal", "-shm"):
        path.with_name(path.name + suffix).chmod(0o644)

    # Reopening must re-pin the pre-existing sidecars to owner-only.
    second = db.connect(path)
    try:
        for suffix in ("-wal", "-shm"):
            sidecar = path.with_name(path.name + suffix)
            assert stat.S_IMODE(sidecar.stat().st_mode) == 0o600, suffix
    finally:
        second.close()
        first.close()


def test_project_subdirectories_are_owner_only(store_root: Path) -> None:
    """Every project subdirectory a write creates ends up with mode 0700.

    A daily-log append creates ``projects``, the per-project directory and its
    ``long-term`` directory in one call; intermediates must be owner-only too,
    not left world-traversable at the umask default.
    """

    ensure_store(store_root)
    append_entry("proj-a", "2026-07-12", "## Note\n\nhello", store_root)

    for relative in ("projects", "projects/proj-a", "projects/proj-a/long-term"):
        directory = store_root / relative
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700, relative


def test_heal_permissions_repins_a_preexisting_loose_tree(store_root: Path) -> None:
    """The heal sweep re-pins subdirectories and files an older install left loose.

    ``ensure_dir`` pins only what it creates, so a store from a version predating
    the invariant keeps its subdirectories world-traversable forever. The
    install-time sweep must correct the whole tree, files included.
    """

    ensure_store(store_root)

    # Stand in for a pre-fix install: a world-traversable project tree holding a
    # world-readable memory file.
    loose_dirs = (
        store_root / "projects",
        store_root / "projects" / "proj-a",
        store_root / "projects" / "proj-a" / "long-term",
    )
    loose_dirs[-1].mkdir(parents=True)
    for directory in loose_dirs:
        directory.chmod(0o755)
    loose_file = loose_dirs[-1] / "2026-07-12.md"
    loose_file.write_text("hello", encoding="utf-8")
    loose_file.chmod(0o644)

    heal_permissions(store_root)

    for directory in loose_dirs:
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700, directory
    assert stat.S_IMODE(loose_file.stat().st_mode) == 0o600, loose_file


def test_write_atomic_produces_an_owner_only_file(store_root: Path) -> None:
    """The shared atomic writer yields a 0600 file even under a loose umask.

    Every short-term, long-term and Concept write goes through ``write_atomic``,
    so the temp file it stages must be owner-only from creation — the replaced
    target is never world-readable, whatever the umask.
    """

    ensure_store(store_root)
    target = store_root / "sensitive.md"

    write_atomic(target, "secret")

    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_uninstall_pointer_is_owner_only(store_root: Path) -> None:
    """The uninstall pointer note is created 0600, not the umask default."""

    ensure_store(store_root)
    pointer = write_uninstall_pointer(store_root)

    assert stat.S_IMODE(pointer.stat().st_mode) == 0o600


def test_failure_log_recreated_owner_only_when_absent(store_root: Path) -> None:
    """``log_failure`` recreates a missing ``mimer.log`` at 0600.

    The last-resort handler can fire before ``ensure_store`` has seeded the log,
    so the append itself must create it owner-only rather than at the umask
    default.
    """

    store_root.mkdir(mode=0o700)
    log_failure("boom", root=store_root)

    log = store_root / LOG_FILENAME
    assert stat.S_IMODE(log.stat().st_mode) == 0o600
