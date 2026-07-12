"""Unit tests for the bounded, rotated dedup ledger (issue #41).

Idempotency keys — captured turn ids, digested session ids, folded commit shas —
need only a *recent* window: an id from long ago is never re-submitted, so the
ledger does not need infinite history to guarantee idempotency. It keeps at most
``capacity`` of the most recently recorded keys in a plain file (ADR 0011: it
works without the derived index), so its size and the cost of a membership check
or a record stay bounded however long a project lives, while dedup of recent keys
still holds.
"""

from __future__ import annotations

from pathlib import Path

from mimer.ledger import DEFAULT_CAPACITY, Ledger


def test_records_and_recognises_a_key(tmp_path: Path) -> None:
    """A recorded key is recognised; an unrecorded one is not."""

    ledger = Ledger(tmp_path / "ledger", capacity=10)
    assert not ledger.contains("a")
    ledger.record("a")
    assert ledger.contains("a")


def test_size_stays_bounded_over_many_records(tmp_path: Path) -> None:
    """The file never grows past ``capacity``, however many keys are recorded."""

    path = tmp_path / "ledger"
    ledger = Ledger(path, capacity=100)
    for i in range(10_000):
        ledger.record(f"key-{i:08d}")
    assert len(path.read_text().split()) <= 100


def test_recent_keys_stay_within_the_window(tmp_path: Path) -> None:
    """The most recently recorded ``capacity`` keys remain recognised (dedup holds)."""

    ledger = Ledger(tmp_path / "ledger", capacity=100)
    for i in range(10_000):
        ledger.record(f"key-{i:08d}")
    assert ledger.contains("key-00009999")
    assert ledger.contains("key-00009900")  # oldest still inside a 100-wide window


def test_keys_beyond_the_window_are_evicted(tmp_path: Path) -> None:
    """A key older than the window is forgotten, which is what bounds the file."""

    ledger = Ledger(tmp_path / "ledger", capacity=100)
    for i in range(10_000):
        ledger.record(f"key-{i:08d}")
    assert not ledger.contains("key-00000000")
    assert not ledger.contains("key-00009899")  # just outside the 100-wide window


def test_extend_records_a_batch_and_trims_once(tmp_path: Path) -> None:
    """A batch of keys is recorded and the window trimmed to the most recent."""

    path = tmp_path / "ledger"
    ledger = Ledger(path, capacity=50)
    ledger.extend(f"sha-{i:08d}" for i in range(500))
    assert len(path.read_text().split()) <= 50
    assert ledger.contains("sha-00000499")
    assert not ledger.contains("sha-00000000")


def test_snapshot_returns_the_current_window(tmp_path: Path) -> None:
    """Snapshot exposes the window as a set for bulk membership tests."""

    ledger = Ledger(tmp_path / "ledger", capacity=10)
    ledger.extend(f"k{i}" for i in range(5))
    assert ledger.snapshot() == {"k0", "k1", "k2", "k3", "k4"}


def test_extend_with_no_keys_is_a_noop(tmp_path: Path) -> None:
    """Recording an empty batch neither creates nor rewrites the file."""

    path = tmp_path / "ledger"
    Ledger(path, capacity=10).extend([])
    assert not path.exists()


def test_default_capacity_covers_the_git_page_window() -> None:
    """The default dedup window stays wider than the git reader's page window: a
    regression guard against lowering capacity to or below it, so a steady-state
    fold's freshly recorded tip shas comfortably outnumber a single read page and
    stay in the window — keeping a reachable commit excluded under linear history
    (#42's reachability fold). The re-fold-free behaviour itself is exercised in
    test_gitreader (#41).
    """

    from mimer.gitreader import _PAGE_SIZE

    assert DEFAULT_CAPACITY > _PAGE_SIZE
