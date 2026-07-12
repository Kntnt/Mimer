"""SQLite connection conventions for the derived search index (ADR 0011).

The index (``index.db``) is derived state, rebuildable from the Markdown files
and never the source of truth. These conventions let concurrent readers and the
detached capture writer coexist:

- **WAL mode** so readers do not block the writer and vice versa.
- **A busy timeout** so a briefly-locked database retries rather than erroring.
- **Insert-or-ignore keyed writes** (a convention the callers use, not enforced
  here) so a double-fired capture cannot duplicate a row.
- **Owner-only permissions** so the index — the single most concentrated copy of
  every project's memory — and its WAL/SHM sidecars stay unreadable to other
  users, not merely masked by the store root's mode (ADR 0013).

The index schema and the ``sqlite-vec`` extension arrive with recall (#9); this
module only standardises how a connection is opened.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from mimer.store import FILE_MODE, ensure_dir

# Default retry window when the database is momentarily locked.
DEFAULT_BUSY_TIMEOUT_MS = 5000

# The WAL sidecars SQLite creates alongside the main database file.
_SIDECAR_SUFFIXES = ("-wal", "-shm")


def connect(path: Path, *, busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS) -> sqlite3.Connection:
    """Open ``path`` as a WAL-mode SQLite database with a busy timeout.

    The index is the single most concentrated copy of every project's memory, so
    the database and its WAL/SHM sidecars are pinned owner-only (ADR 0013). The
    main file is chmod-ed before the WAL pragma materialises the sidecars —
    SQLite copies the main file's mode onto them — and any sidecar predating this
    connection is corrected too, so the invariant holds regardless of order.

    Args:
        path: The database file; its parent directory is created owner-only if
            absent, so the connection never races ahead of the store's mode.
        busy_timeout_ms: How long a statement waits on a locked database before
            raising, in milliseconds.

    Returns:
        A configured :class:`sqlite3.Connection`; use it as a context manager.
    """

    # Ensure the parent exists owner-only, then create the database file at the
    # store file mode so the sidecars SQLite makes next inherit it.
    ensure_dir(path.parent)
    if not path.exists():
        path.touch(mode=FILE_MODE)
    path.chmod(FILE_MODE)

    # WAL and the busy timeout are the concurrency-critical pragmas; both persist
    # for the connection (WAL persists for the database file).
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")

    # Correct any sidecar that predates this connection (a prior session may have
    # left it at a looser mode); freshly created ones already inherited FILE_MODE.
    for suffix in _SIDECAR_SUFFIXES:
        sidecar = path.with_name(path.name + suffix)
        if sidecar.exists():
            sidecar.chmod(FILE_MODE)

    return connection
