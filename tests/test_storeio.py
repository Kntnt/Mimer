"""Concurrency tests for the store I/O layer (ADR 0011): per-project locked
read-modify-write serialises without lost updates, O_APPEND daily-log writes
interleave without loss, and a crashed lock holder never deadlocks the store.

The advisory locks are also thread-reentrant (#49): the same thread nests a
project, named, or mixed lock without self-deadlocking, the hold releases only
when the outermost holder exits, and distinct names — including a project id and
a named lock spelled the same — are independent locks.

The write seam (#55): every write primitive runs the redaction pass before bytes
reach disk, so a raw secret written through any of the three lands redacted,
while shape-safe provenance lands byte-identical.
"""

from __future__ import annotations

import multiprocessing
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from mimer.store import ensure_store
from mimer.storeio import append_fold, append_text, named_lock, project_lock, write_atomic
from tests.secret_samples import SAMPLES, SHAPE_SAFE, Sample


def _locked_append(target: Path, marker: str, root: Path) -> None:
    """Append ``marker`` to ``target`` as a locked read-modify-write.

    The brief pause widens the read-modify-write window so an unlocked
    implementation would reliably lose updates — proving the lock is what
    protects them. This is the raw ``project_lock`` + ``write_atomic`` discipline
    short-term memory now takes through ``shortterm.rewrite_sections``.
    """

    with project_lock("proj", root=root):
        current = target.read_text(encoding="utf-8") if target.exists() else ""
        time.sleep(0.01)
        write_atomic(target, current + marker + "\n")


def test_locked_rmw_has_no_lost_updates(store_root: Path, tmp_path: Path) -> None:
    """Many concurrent locked read-modify-writes to one file all survive: the
    per-project lock around ``write_atomic`` serialises them with no lost update."""

    ensure_store(store_root)
    target = tmp_path / "short-term.md"
    target.write_text("", encoding="utf-8")

    writers = [f"line-{i}" for i in range(15)]

    def write(marker: str) -> None:
        _locked_append(target, marker, store_root)

    threads = [threading.Thread(target=write, args=(m,)) for m in writers]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    lines = set(target.read_text().splitlines())
    assert lines == set(writers)


def test_concurrent_appends_lose_nothing(store_root: Path, tmp_path: Path) -> None:
    """Concurrent O_APPEND writers to one daily log interleave without loss or
    corruption — the timing-based stress case."""

    ensure_store(store_root)
    log = tmp_path / "2026-07-11.md"

    threads_count = 20
    per_thread = 50

    def append_many(worker: int) -> None:
        for n in range(per_thread):
            append_text(log, f"w{worker}-n{n}")

    threads = [threading.Thread(target=append_many, args=(w,)) for w in range(threads_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    lines = log.read_text().splitlines()
    assert len(lines) == threads_count * per_thread
    # Every line is intact (no torn writes) and unique.
    assert len(set(lines)) == threads_count * per_thread
    assert all(line.startswith("w") for line in lines)


def test_lock_release_allows_reacquire(store_root: Path) -> None:
    """A released lock can be acquired again; a held one is exclusive."""

    ensure_store(store_root)

    with project_lock("proj", root=store_root):
        pass
    # Re-acquisition after clean release must not block.
    with project_lock("proj", root=store_root):
        pass


def test_held_lock_serialises_a_waiter(store_root: Path) -> None:
    """A second acquirer waits until the first releases (contention is real)."""

    ensure_store(store_root)
    events: list[str] = []

    holder_has_lock = threading.Event()
    release_holder = threading.Event()

    def holder() -> None:
        with project_lock("proj", root=store_root):
            events.append("holder-acquired")
            holder_has_lock.set()
            release_holder.wait(2)
            events.append("holder-releasing")

    def waiter() -> None:
        holder_has_lock.wait(2)
        with project_lock("proj", root=store_root):
            events.append("waiter-acquired")

    threads = [threading.Thread(target=holder), threading.Thread(target=waiter)]
    for thread in threads:
        thread.start()
    time.sleep(0.1)
    release_holder.set()
    for thread in threads:
        thread.join(3)

    # The waiter only got in after the holder released.
    assert events == ["holder-acquired", "holder-releasing", "waiter-acquired"]


def _hold_then_hang(project_id: str, root: str, ready: str) -> None:
    """Child process: grab the lock, announce it, then hang until killed."""

    from pathlib import Path

    from mimer.storeio import project_lock

    with project_lock(project_id, root=Path(root)):
        Path(ready).write_text("ready", encoding="utf-8")
        time.sleep(120)


def test_crashed_holder_does_not_deadlock(store_root: Path, tmp_path: Path) -> None:
    """A lock holder killed with SIGKILL leaves the lock recoverable."""

    ensure_store(store_root)
    ready = tmp_path / "ready"

    ctx = multiprocessing.get_context("spawn")
    child = ctx.Process(target=_hold_then_hang, args=("proj", str(store_root), str(ready)))
    child.start()

    # Wait until the child actually holds the lock, then hard-kill it.
    deadline = time.time() + 15
    while not ready.exists() and time.time() < deadline:
        time.sleep(0.05)
    assert ready.exists(), "child never acquired the lock"
    child.kill()
    child.join(10)

    # The parent must be able to acquire the lock the crashed child abandoned.
    acquired = threading.Event()

    def acquire() -> None:
        with project_lock("proj", root=store_root):
            acquired.set()

    grabber = threading.Thread(target=acquire)
    grabber.start()
    grabber.join(5)
    assert acquired.is_set(), "the lock deadlocked after a crash"


def _completes_within(target: Callable[[], None], timeout: float = 5.0) -> bool:
    """Run ``target`` on a daemon thread; return whether it finished in time.

    A lock that self-deadlocks on a reentrant acquisition never returns, so a
    timed-out worker is the observable signature of the bug these tests guard
    against. The worker is a daemon so a genuinely wedged thread — the failure
    being asserted — never blocks the rest of the suite, and each test owns its
    own store root, so an abandoned holder cannot leak into another test.
    """

    done = threading.Event()

    def run() -> None:
        target()
        done.set()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return done.wait(timeout)


def test_same_thread_reentrant_project_lock(store_root: Path) -> None:
    """The same thread nests one project lock without self-deadlocking."""

    ensure_store(store_root)

    def nest() -> None:
        with project_lock("proj", root=store_root), project_lock("proj", root=store_root):
            pass

    assert _completes_within(nest), "same-thread project_lock nesting deadlocked"


def test_same_thread_reentrant_named_lock(store_root: Path) -> None:
    """The same thread nests one named lock without self-deadlocking."""

    ensure_store(store_root)

    def nest() -> None:
        with named_lock("bundle", root=store_root), named_lock("bundle", root=store_root):
            pass

    assert _completes_within(nest), "same-thread named_lock nesting deadlocked"


def test_same_thread_reentrant_mixed_locks(store_root: Path) -> None:
    """One thread holds a project lock and a named lock (distinct names) at once,
    nesting each, without deadlock."""

    ensure_store(store_root)

    def nest() -> None:
        with (
            project_lock("proj", root=store_root),
            named_lock("bundle", root=store_root),
            project_lock("proj", root=store_root),
            named_lock("bundle", root=store_root),
        ):
            pass

    assert _completes_within(nest), "mixed same-thread lock nesting deadlocked"


def test_nested_hold_releases_only_at_outermost_exit(store_root: Path) -> None:
    """A reentrant hold stays exclusive until the outermost holder exits: a waiter
    in another thread gets in only after the outer block ends, never when the
    inner one does."""

    ensure_store(store_root)

    outer_entered = threading.Event()
    inner_exited = threading.Event()
    allow_outer_exit = threading.Event()
    waiter_acquired = threading.Event()

    def holder() -> None:
        with project_lock("proj", root=store_root):
            outer_entered.set()
            with project_lock("proj", root=store_root):
                pass
            inner_exited.set()
            allow_outer_exit.wait(2)

    def waiter() -> None:
        outer_entered.wait(2)
        with project_lock("proj", root=store_root):
            waiter_acquired.set()

    threads = [
        threading.Thread(target=holder, daemon=True),
        threading.Thread(target=waiter, daemon=True),
    ]
    for thread in threads:
        thread.start()

    # The inner block must exit (proving the nest did not deadlock) while the lock
    # is still held, so the waiter cannot have acquired it yet.
    assert inner_exited.wait(2), "nested project_lock acquisition deadlocked"
    time.sleep(0.1)
    assert not waiter_acquired.is_set(), "the lock released when the inner hold exited"

    # Only once the outermost hold exits may the waiter proceed.
    allow_outer_exit.set()
    for thread in threads:
        thread.join(3)
    assert waiter_acquired.is_set(), "the waiter never acquired the released lock"


def test_distinct_named_locks_are_independent(store_root: Path) -> None:
    """Two named locks with different names never serialise against each other."""

    ensure_store(store_root)

    alpha_held = threading.Event()
    beta_acquired = threading.Event()
    release_alpha = threading.Event()

    def hold_alpha() -> None:
        with named_lock("alpha", root=store_root):
            alpha_held.set()
            release_alpha.wait(2)

    def take_beta() -> None:
        alpha_held.wait(2)
        with named_lock("beta", root=store_root):
            beta_acquired.set()

    threads = [
        threading.Thread(target=hold_alpha, daemon=True),
        threading.Thread(target=take_beta, daemon=True),
    ]
    for thread in threads:
        thread.start()

    # `beta` must be acquirable while `alpha` is still held; independence means no
    # wait on the unrelated name.
    assert beta_acquired.wait(2), "a distinct named lock blocked on an unrelated one"
    release_alpha.set()
    for thread in threads:
        thread.join(3)


def test_named_lock_and_project_lock_do_not_collide(store_root: Path) -> None:
    """A project id and a named lock spelled the same are independent locks: the
    dunder lock-file naming keeps them in disjoint files."""

    ensure_store(store_root)

    project_held = threading.Event()
    named_acquired = threading.Event()
    release_project = threading.Event()

    def hold_project() -> None:
        with project_lock("registry", root=store_root):
            project_held.set()
            release_project.wait(2)

    def take_named() -> None:
        project_held.wait(2)
        with named_lock("registry", root=store_root):
            named_acquired.set()

    threads = [
        threading.Thread(target=hold_project, daemon=True),
        threading.Thread(target=take_named, daemon=True),
    ]
    for thread in threads:
        thread.start()

    # The named lock must be acquirable while the same-spelled project lock is
    # held — a marker-chosen project id can never collide with a lock name.
    assert named_acquired.wait(2), "named_lock collided with a same-named project_lock"
    release_project.set()
    for thread in threads:
        thread.join(3)


def test_named_lock_uses_dunder_lock_file(store_root: Path) -> None:
    """A named lock's file keeps the dunder naming, so it cannot collide with a
    sanitised project id's lock file."""

    ensure_store(store_root)

    with named_lock("registry", root=store_root):
        assert (store_root / "locks" / "__registry__.lock").exists()


# The three write primitives, keyed by name, and the on-disk transform each
# applies to already-safe content: write_atomic and append_fold write byte for
# byte; append_text normalises to exactly one trailing newline. Both seam tests
# below drive every primitive so the disk guarantee has no per-primitive gap.
_WRITE_PRIMITIVES: list[Callable[[Path, str], None]] = [write_atomic, append_text, append_fold]

_ON_DISK: dict[str, Callable[[str], str]] = {
    "write_atomic": lambda s: s,
    "append_fold": lambda s: s,
    "append_text": lambda s: s.rstrip("\n") + "\n",
}


@pytest.mark.parametrize("primitive", _WRITE_PRIMITIVES, ids=lambda p: p.__name__)
@pytest.mark.parametrize("sample", SAMPLES, ids=lambda s: s.name)
def test_write_primitive_strips_a_secret(
    primitive: Callable[[Path, str], None], sample: Sample, tmp_path: Path
) -> None:
    """A raw secret written through any write primitive lands redacted on disk:
    the seam runs the redaction pass before bytes reach the file, so no sink has
    to remember to."""

    target = tmp_path / "artefact"
    primitive(target, f"here is the value {sample.text} use it")

    content = target.read_text(encoding="utf-8")
    assert sample.sensitive not in content
    assert "REDACTED" in content


@pytest.mark.parametrize("primitive", _WRITE_PRIMITIVES, ids=lambda p: p.__name__)
@pytest.mark.parametrize("identifier", SHAPE_SAFE)
def test_write_primitive_keeps_shape_safe_content_byte_identical(
    primitive: Callable[[Path, str], None], identifier: str, tmp_path: Path
) -> None:
    """Shape-safe provenance — git SHAs, ULIDs, normalised remotes, ISO dates,
    ledger hashes — written through any write primitive lands byte-identical: the
    seam's redaction is shape-based, so the identifiers Mimer cites survive."""

    target = tmp_path / "artefact"
    payload = f"provenance {identifier} kept"
    primitive(target, payload)

    assert target.read_text(encoding="utf-8") == _ON_DISK[primitive.__name__](payload)
