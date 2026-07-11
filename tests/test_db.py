"""Tests for the SQLite connection conventions used by the derived index (ADR
0011): WAL mode and a busy timeout, so concurrent readers and the detached
capture writer coexist. The index schema itself arrives in #9.
"""

from __future__ import annotations

from pathlib import Path

from mimer.db import connect


def test_connection_uses_wal_and_busy_timeout(tmp_path: Path) -> None:
    """A connection opens in WAL mode with the configured busy timeout."""

    db_path = tmp_path / "index.db"

    with connect(db_path, busy_timeout_ms=3000) as connection:
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]

    assert journal_mode.lower() == "wal"
    assert busy_timeout == 3000


def test_insert_or_ignore_is_idempotent_on_key(tmp_path: Path) -> None:
    """The insert-or-ignore convention makes a double write a no-op on its key —
    the pattern capture relies on for idempotency (#6)."""

    db_path = tmp_path / "index.db"

    with connect(db_path) as connection:
        connection.execute("CREATE TABLE t (key TEXT PRIMARY KEY, value TEXT)")
        connection.execute("INSERT OR IGNORE INTO t (key, value) VALUES ('k', 'first')")
        connection.execute("INSERT OR IGNORE INTO t (key, value) VALUES ('k', 'second')")
        rows = connection.execute("SELECT key, value FROM t").fetchall()

    assert rows == [("k", "first")]
