"""Concurrency-safe store I/O (ADR 0011).

Multiple sessions and detached capture processes touch the store at once, so
every shared Markdown artefact gets an explicit discipline:

- **Read-modify-write** of a file takes a per-project advisory lock and re-reads
  inside it (:func:`update_file`), so two writers serialise and neither update is
  lost.
- **Daily-log entries** are pure appends written with ``O_APPEND``
  (:func:`append_text`), so concurrent writers interleave whole lines without a
  lock and without corruption.

Advisory locks use ``flock``, which the kernel releases automatically when the
holding process dies — so a crashed holder never deadlocks the store.
"""

from __future__ import annotations

import fcntl
import os
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from mimer.paths import store_root
from mimer.store import FILE_MODE, ensure_store

# Per-project advisory locks live here, one file per project id.
LOCKS_DIRNAME = "locks"


def _lock_path(project_id: str, root: Path) -> Path:
    """Path to a project's advisory lock file, with a filesystem-safe name."""

    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", project_id).strip("-.") or "project"
    return root / LOCKS_DIRNAME / f"{safe}.lock"


@contextmanager
def project_lock(project_id: str, *, root: Path | None = None) -> Iterator[None]:
    """Hold the exclusive per-project advisory lock for the duration of the block.

    The lock file is created on demand. ``flock`` is advisory and released by the
    kernel when this process exits, so a crash cannot leave the store wedged.
    """

    root = root or store_root()
    ensure_store(root)

    lock_file = _lock_path(project_id, root)
    lock_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)

    # Open (creating if needed) and take an exclusive lock, releasing on exit.
    fd = os.open(lock_file, os.O_RDWR | os.O_CREAT, FILE_MODE)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def append_text(path: Path, text: str) -> None:
    """Append ``text`` as one newline-terminated record using ``O_APPEND``.

    A single ``O_APPEND`` write lands atomically at end-of-file, so concurrent
    appenders never interleave within a record. Records are kept short (a bullet
    or a small group) to stay within the platform's atomic-write bound.
    """

    path.parent.mkdir(parents=True, exist_ok=True)

    data = (text.rstrip("\n") + "\n").encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, FILE_MODE)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def write_atomic(path: Path, content: str) -> None:
    """Write ``content`` to ``path`` atomically (temp file then ``os.replace``).

    A reader never sees a half-written file. Callers that need mutual exclusion
    must already hold the relevant :func:`project_lock`.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.chmod(FILE_MODE)
    os.replace(tmp, path)


def update_file(
    path: Path,
    transform: Callable[[str], str],
    *,
    project_id: str,
    root: Path | None = None,
) -> str:
    """Read-modify-write ``path`` under the project lock, returning new content.

    The file is re-read inside the lock and rewritten atomically, so a concurrent
    writer cannot lose an update. A missing file is treated as empty.
    """

    root = root or store_root()

    with project_lock(project_id, root=root):
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        updated = transform(current)
        write_atomic(path, updated)

    return updated
