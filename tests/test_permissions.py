"""Owner-only permission invariant (ADR 0013, issue #26).

The store concentrates every project's memory in one place, so every file and
directory Mimer creates must be owner-only on its own — not merely because the
0700 root happens to mask it. The index (``index.db``) is the single most
concentrated copy of all projects' memory text; its WAL/SHM sidecars carry the
same content. These tests pin the two paths that historically drifted: the index
database and its sidecars (0600), and the project subdirectories created as
intermediates of a deeper write (0700).
"""

from __future__ import annotations

import stat
from pathlib import Path

from mimer import db
from mimer.index import index_db_path
from mimer.longterm import append_entry
from mimer.store import ensure_store


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
        for suffix in ("", "-wal", "-shm"):
            sidecar = path.with_name(path.name + suffix)
            assert sidecar.exists(), f"expected {suffix or 'index.db'} to exist"
            assert stat.S_IMODE(sidecar.stat().st_mode) == 0o600, suffix or "index.db"
    finally:
        connection.close()


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
