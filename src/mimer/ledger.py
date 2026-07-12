"""A bounded, rotated dedup ledger (issue #41).

The capture, digest and git ledgers exist for one job: idempotency. They answer
"have I already recorded this turn / session / commit?" so a double-fired hook or
a re-run reader records nothing twice. A double-fire only recurs for a *recent*
id — an id from months ago is never re-submitted — so a ledger needs a bounded
window of recent ids, not infinite history.

This module holds exactly that window in a plain file, one id per line: it stays
a plain file so dedup survives an index-free store (ADR 0011). It is *meant* to
keep at most ``capacity`` of the most recently recorded ids, evicting the oldest,
so the file's size and the cost of a membership check or a record stay bounded
however long a project lives. This first cut does not yet evict — the failing
tests (#41) demand the bound the green step adds.

A record is a read-modify-write, so — like any store artefact rewritten in place
(ADR 0011) — the caller must hold the per-project lock. Capture, the digest and
the git reader all do.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from mimer.storeio import write_atomic

# The rotated window's default size: how many recent ids to keep for dedup. It
# comfortably exceeds the git reader's commit window (gitreader._COMMIT_LIMIT), so
# under linear history a commit still reachable by `git log` stays inside the
# window and is not re-folded; only branch switching that folds more than a
# window's worth of other commits can evict a reachable sha and re-fold it once.
# It is a "simplest that works" bound, tunable in one place on a real limit — a
# 16-hex-char turn id costs ~17 bytes, so 1000 ids is a ~17 KB file.
DEFAULT_CAPACITY = 1000


@dataclass(frozen=True)
class Ledger:
    """A dedup window of the most recent ``capacity`` keys, kept in a plain file.

    Keys are whitespace-free tokens (turn ids, session ids, commit shas). Reads
    are safe without coordination; :meth:`record` and :meth:`extend` rewrite the
    file and so require the caller to hold the relevant project lock.
    """

    path: Path
    capacity: int = DEFAULT_CAPACITY

    def contains(self, key: str) -> bool:
        """Whether ``key`` is inside the current window."""

        return key in self.snapshot()

    def snapshot(self) -> set[str]:
        """The current window as a set, for bulk membership tests."""

        return set(self._load())

    def record(self, key: str) -> None:
        """Add one ``key`` to the window."""

        self.extend((key,))

    def extend(self, keys: Iterable[str]) -> None:
        """Add ``keys`` to the window in order.

        A batch keeps the write to a single rewrite. An empty batch is a no-op —
        it neither creates nor rewrites the file.
        """

        additions = list(keys)
        if not additions:
            return

        # Append after the existing window. NOTE (#41): this first cut does not yet
        # bound the window — the eviction the failing tests demand is the green step.
        window = self._load()
        window.extend(additions)
        write_atomic(self.path, "\n".join(window) + "\n")

    def _load(self) -> list[str]:
        """The current window as an ordered list (oldest first); [] when absent."""

        if not self.path.exists():
            return []
        return self.path.read_text(encoding="utf-8").split()
