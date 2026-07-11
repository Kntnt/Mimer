"""SQLite connection conventions for the derived search index (ADR 0011).

The index (``index.db``) is derived state, rebuildable from the Markdown files
and never the source of truth. These conventions let concurrent readers and the
detached capture writer coexist:

- **WAL mode** so readers do not block the writer and vice versa.
- **A busy timeout** so a briefly-locked database retries rather than erroring.
- **Insert-or-ignore keyed writes** (a convention the callers use, not enforced
  here) so a double-fired capture cannot duplicate a row.

The index schema and the ``sqlite-vec`` extension arrive with recall (#9); this
module only standardises how a connection is opened.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

# Default retry window when the database is momentarily locked.
DEFAULT_BUSY_TIMEOUT_MS = 5000


def connect(path: Path, *, busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS) -> sqlite3.Connection:
    """Open ``path`` as a WAL-mode SQLite database with a busy timeout.

    Args:
        path: The database file (its parent directory is created if absent).
        busy_timeout_ms: How long a statement waits on a locked database before
            raising, in milliseconds.

    Returns:
        A configured :class:`sqlite3.Connection`; use it as a context manager.
    """

    path.parent.mkdir(parents=True, exist_ok=True)

    # WAL and the busy timeout are the concurrency-critical pragmas; both persist
    # for the connection (WAL persists for the database file).
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
    return connection
