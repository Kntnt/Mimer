"""Concurrency-safe store I/O and the store's write-discipline map (ADR 0011).

Multiple sessions and detached capture processes touch the store at once, so
every shared artefact has one explicit write discipline. This module is the
single home of that map, and the primitive that implements each row:

======================================  =============================  ===========================
Artefact                                Discipline                     Primitive
======================================  =============================  ===========================
short-term memory (short-term.md)       locked RMW (per-project lock)  project_lock + write_atomic
capture/digest/git ledgers (#41)        locked RMW (per-project lock)  project_lock + write_atomic
the permanent bundle (+ index.md)       locked RMW (store-wide named)  named_lock + write_atomic
the registry (registry.json)            locked RMW (store-wide named)  named_lock + write_atomic
daily-log entries                       lockless O_APPEND              append_text
announcement queue (.distilled-queue)   lockless O_APPEND              append_text
tombstones (tombstones.jsonl)           lockless O_APPEND              append_text
project-merge folds (ADR 0008)          lockless O_APPEND fold         append_fold
======================================  =============================  ===========================

*Locked read-modify-write* re-reads the file inside the lock and rewrites it
atomically — an explicit :func:`project_lock` / :func:`named_lock` around
:func:`write_atomic` (short-term memory wraps this pair in
:func:`mimer.shortterm.rewrite_sections`) — so two writers serialise and neither
update is lost. *Lockless O_APPEND* writes each short record with
``O_APPEND`` (:func:`append_text`), so concurrent writers interleave whole
records without a lock and without corruption; a project merge (ADR 0008) folds
a whole append-only block the same way (:func:`append_fold`), so the fold can
neither clobber nor be clobbered by a concurrent appender.

The announcement queue (``.distilled-queue``) is the one append-only artefact
that also takes a **locked clear**: :func:`mimer.distill._clear_announcements`
re-reads it and rewrites the survivors with :func:`write_atomic` (or ``unlink``
when none remain) under :func:`project_lock`. Its enqueues stay lockless
``O_APPEND`` only because every enqueue runs under the caller's project lock —
the session digest's :func:`mimer.shortterm.rewrite_sections` — so a title
appended concurrently cannot be lost in the window between the clear's read and
its write (the #40 lost update). A future writer
that added a truly lockless enqueue would reopen that lost update, so the
under-lock invariant is load-bearing, not incidental.

Every write primitive — :func:`write_atomic`, :func:`append_text`,
:func:`append_fold` — runs the redaction pass (:func:`mimer.redaction.redact`) on
its content before bytes reach disk (ADR 0020), so the module's contract is one
sentence: *no text reaches the store's files unredacted* through here. A sink that
forgets to redact can no longer leak; the guarantee holds where bytes hit disk,
not at each call site. Redaction is shape-based, so the provenance the rest of
Mimer cites — git SHAs, ULIDs, normalised remotes, ISO dates, ledger hashes —
passes through byte-identical. The one deliberate exemption is the capture spool:
a transient 0600 hand-off inside the 0700 store, consumed and deleted in a
``finally`` and never routed through these primitives — its content is redacted
when persisted, and the raw transcript exists outside the store regardless, so
redacting the spool would only add regex cost to the latency-sensitive Stop hook
and defend nothing the platform does not already expose.

Advisory locks (:func:`project_lock`, :func:`named_lock`) share one reentrant
``flock`` mechanism whose contract is:

- reentrant within one thread — the same thread nests the same lock freely;
- threads exclude each other — a second thread blocks until the first releases;
- processes exclude each other — a second process blocks likewise;
- ``project_lock`` and ``named_lock`` share the mechanism, and different names
  are independent locks.

``flock`` is released by the kernel when the holding process dies, so a crashed
holder never wedges the store.
"""

from __future__ import annotations

import fcntl
import os
import re
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from mimer.paths import store_root
from mimer.redaction import redact
from mimer.store import FILE_MODE, ensure_dir, ensure_store

# Advisory lock files live here, one per project id or store-wide name.
LOCKS_DIRNAME = "locks"


@dataclass
class _LockHold:
    """One thread's hold on a lock file: the open fd and how deep the nest is.

    The kernel ``flock`` is taken once when ``depth`` first reaches 1 and released
    only when it falls back to 0, so a reentrant acquisition never re-locks and
    the whole nest presents unbroken exclusion to other threads and processes.
    """

    fd: int
    depth: int


class _HeldLocks(threading.local):
    """Per-thread table of the advisory locks this thread currently holds.

    ``threading.local`` re-runs ``__init__`` in every thread, so each thread sees
    its own empty table — the basis of the reentrancy. A thread finds and deepens
    only locks it took itself; a lock another thread holds is invisible here and
    excluded through the kernel ``flock`` instead, which conflicts two fds on one
    file even within a single process (the self-deadlock this table removes).
    """

    def __init__(self) -> None:
        self.table: dict[tuple[Path, Path], _LockHold] = {}


_held = _HeldLocks()


def _lock_path(project_id: str, root: Path) -> Path:
    """Path to a project's advisory lock file, with a filesystem-safe name."""

    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", project_id).strip("-.") or "project"
    return root / LOCKS_DIRNAME / f"{safe}.lock"


def _named_lock_path(name: str, root: Path) -> Path:
    """Path to a store-wide named lock file.

    The dunder wrapping keeps every named lock in a namespace no sanitised project
    id (``locks/<safe>.lock``) can reach, so a marker-chosen project id and a lock
    name spelled the same never resolve to the same file.
    """

    return root / LOCKS_DIRNAME / f"__{name}__.lock"


@contextmanager
def _hold(root: Path, lock_file: Path) -> Iterator[None]:
    """Hold ``lock_file`` exclusively for the block, reentrant within one thread.

    The single mechanism behind :func:`project_lock` and :func:`named_lock`. The
    first acquisition on a thread opens the file and takes the kernel ``flock``; a
    nested acquisition of the same lock reuses that fd and only deepens the count,
    so a thread never blocks on a lock it already holds. The ``flock`` is released
    — and the fd closed — only when the outermost hold exits.
    """

    table = _held.table
    key = (root, lock_file)
    hold = table.get(key)

    # First acquisition on this thread: open the lock file and take the exclusive
    # kernel flock, closing the fd if the lock itself fails so it never leaks.
    if hold is None:
        fd = os.open(lock_file, os.O_RDWR | os.O_CREAT, FILE_MODE)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
        except BaseException:
            os.close(fd)
            raise
        hold = _LockHold(fd=fd, depth=0)
        table[key] = hold

    # Deepen the nest for the block, releasing the kernel flock and closing the fd
    # only as the outermost hold unwinds.
    hold.depth += 1
    try:
        yield
    finally:
        hold.depth -= 1
        if hold.depth == 0:
            del table[key]
            fcntl.flock(hold.fd, fcntl.LOCK_UN)
            os.close(hold.fd)


@contextmanager
def named_lock(name: str, *, root: Path | None = None) -> Iterator[None]:
    """Hold the store-wide artefact lock named ``name`` for the block.

    The home of the store's cross-cutting locks — the registry, the permanent
    bundle — that belong to no single project. The lock file is
    ``locks/__<name>__.lock``; the dunder wrapping keeps it clear of every
    project's ``locks/<safe>.lock``, so a marker-chosen project id can never
    collide with a lock name.

    The lock is reentrant within one thread and mutually exclusive across threads
    and processes; :func:`project_lock` is its per-project counterpart on the same
    mechanism, and different names are independent locks. ``flock`` is released by
    the kernel when the holder dies, so a crash cannot wedge the store.
    """

    root = root or store_root()
    ensure_store(root)

    lock_file = _named_lock_path(name, root)
    ensure_dir(lock_file.parent)

    with _hold(root, lock_file):
        yield


@contextmanager
def project_lock(project_id: str, *, root: Path | None = None) -> Iterator[None]:
    """Hold the exclusive per-project advisory lock for the duration of the block.

    Shares the reentrant ``flock`` mechanism with :func:`named_lock`, its
    store-wide counterpart, so the same thread may nest this lock freely while
    threads and processes still exclude one another. The lock file is created on
    demand and released by the kernel when this process exits, so a crash cannot
    leave the store wedged.
    """

    root = root or store_root()
    ensure_store(root)

    lock_file = _lock_path(project_id, root)
    ensure_dir(lock_file.parent)

    with _hold(root, lock_file):
        yield


def append_text(path: Path, text: str) -> None:
    """Append ``text`` as one newline-terminated record using ``O_APPEND``.

    A single ``O_APPEND`` write lands atomically at end-of-file, so concurrent
    appenders never interleave within a record. Records are kept short (a bullet
    or a small group) to stay within the platform's atomic-write bound. The text
    is redacted at the write seam first (ADR 0020).
    """

    ensure_dir(path.parent)

    # Strip secrets at the write seam (ADR 0020), then frame the record as one
    # newline-terminated line.
    data = (redact(text).rstrip("\n") + "\n").encode("utf-8")
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
    keeps the store's owner-only mode. The content is redacted at the write seam
    first (ADR 0020) — the fold moves already-redacted artefacts, but if a secret
    ever leaked past an earlier version the fold is a free sanitation.
    """

    # Strip secrets at the write seam (ADR 0020), then append every byte at
    # end-of-file: O_APPEND makes each write seek-and-land atomically, and the
    # loop covers a short os.write, so a large fold is never truncated and a
    # concurrent appender only ever interleaves whole records.
    data = redact(content).encode("utf-8")
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
    hold the relevant :func:`project_lock`. The content is redacted at the write
    seam first (ADR 0020).
    """

    ensure_dir(path.parent)

    # Strip secrets at the write seam (ADR 0020), then stage the content in a temp
    # file that is owner-only from creation and replace the target atomically; the
    # unique name also stops two concurrent writers colliding on a shared temp path.
    handle, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as tmp_file:
            tmp_file.write(redact(content))
        os.chmod(tmp_name, FILE_MODE)
        os.replace(tmp_name, path)
    except BaseException:
        # Reap the staged temp on any failure before the swap lands — including
        # KeyboardInterrupt — so repeated mid-write failures never accumulate
        # orphan .tmp files beside the real store artefacts.
        Path(tmp_name).unlink(missing_ok=True)
        raise
