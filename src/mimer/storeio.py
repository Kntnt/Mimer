"""Concurrency-safe store I/O (ADR 0011).

Multiple sessions and detached capture processes touch the store at once, so
every shared Markdown artefact gets an explicit discipline:

- **Read-modify-write** of a file takes a per-project advisory lock and re-reads
  inside it (:func:`update_file`), so two writers serialise and neither update is
  lost.
- **Daily-log entries** are pure appends written with ``O_APPEND``
  (:func:`append_text`), so concurrent writers interleave whole lines without a
  lock and without corruption.
- **Whole-artefact folds** — a project merge (ADR 0008) combining one append-only
  file onto another — use :func:`append_fold`, the same ``O_APPEND`` discipline
  over a full block, so the fold can neither clobber nor be clobbered by a
  concurrent appender.

Advisory locks use ``flock``, which the kernel releases automatically when the
holding process dies — so a crashed holder never deadlocks the store.
"""

from __future__ import annotations

import fcntl
import os
import re
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from mimer.paths import store_root
from mimer.store import FILE_MODE, ensure_dir, ensure_store

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
    ensure_dir(lock_file.parent)

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

    ensure_dir(path.parent)

    data = (text.rstrip("\n") + "\n").encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, FILE_MODE)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def append_fold(path: Path, content: str) -> None:
    """Fold ``content`` onto the end of ``path`` with ``O_APPEND``, byte for byte.

    Unlike :func:`append_text`, which writes one short, newline-terminated record,
    this appends an arbitrary-length block and writes *every* byte — a single
    ``os.write`` can fall short for a large fold — so nothing is truncated. Each
    write lands at the current end-of-file, so the fold can neither overwrite the
    target's existing records nor be overwritten by a concurrent
    :func:`append_text` producer, whatever lock either side holds. A project merge
    (ADR 0008) uses it to combine one append-only artefact onto another; the target
    keeps the store's owner-only mode.
    """

    # Append every byte at end-of-file: O_APPEND makes each write seek-and-land
    # atomically, and the loop covers a short os.write, so a large fold is never
    # truncated and a concurrent appender only ever interleaves whole records.
    data = content.encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, FILE_MODE)
    try:
        offset = 0
        while offset < len(data):
            offset += os.write(fd, data[offset:])
    finally:
        os.close(fd)

    # Re-assert the store's owner-only mode: O_APPEND onto an existing file leaves
    # its mode untouched, so a target loosened out-of-band is tightened here.
    os.chmod(path, FILE_MODE)


def write_atomic(path: Path, content: str) -> None:
    """Write ``content`` to ``path`` atomically and owner-only from creation.

    A reader never sees a half-written file, and the file is never momentarily
    world-readable: the content lands in a uniquely-named temp file in the target
    directory that ``mkstemp`` creates at 0600 from birth — closing the window a
    ``write_text``-then-``chmod`` would open (issue #26) — before an atomic
    ``os.replace`` swaps it in. Callers that need mutual exclusion must already
    hold the relevant :func:`project_lock`.
    """

    ensure_dir(path.parent)

    # Stage the content in a temp file that is owner-only from creation, then
    # replace the target atomically; the unique name also stops two concurrent
    # writers colliding on a shared temp path.
    handle, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as tmp_file:
            tmp_file.write(content)
        os.chmod(tmp_name, FILE_MODE)
        os.replace(tmp_name, path)
    except BaseException:
        # Reap the staged temp on any failure before the swap lands — including
        # KeyboardInterrupt — so repeated mid-write failures never accumulate
        # orphan .tmp files beside the real store artefacts.
        Path(tmp_name).unlink(missing_ok=True)
        raise


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
