"""A bounded, rotated dedup ledger (issue #41).

The capture ledger exists for one job: idempotency. It answers "have I already
recorded this turn?" so a double-fired Stop hook records nothing twice. A
double-fire only recurs for a *recent* id — an id from months ago is never
re-submitted — so a ledger needs a bounded window of recent ids, not infinite
history.

This module holds exactly that window in a plain file, one id per line: it stays
a plain file so dedup survives an index-free store (ADR 0011), and it keeps at
most ``capacity`` of the most recently recorded ids, evicting the oldest. Both
the file's size and the cost of a membership check or a record therefore stay
bounded however long a project lives, instead of growing one id per turn forever.

A record is a read-modify-write, so — like any store artefact rewritten in place
(ADR 0011) — the caller must hold the per-project lock. Capture does.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from mimer.storeio import write_atomic

# The rotated window's default size: how many recent ids to keep for dedup. It is
# a "simplest that works" bound, tunable in one place on a real limit — a
# 16-hex-char turn id costs ~17 bytes, so 1000 ids is a ~17 KB file — and it sits
# far above the number of turns any single session double-fires, so a re-fired
# Stop hook always finds its turn still inside the window.
DEFAULT_CAPACITY = 1000


@dataclass(frozen=True)
class Ledger:
    """A dedup window of the most recent ``capacity`` keys, kept in a plain file.

    Keys are whitespace-free tokens (turn ids). Reads are safe without
    coordination; :meth:`record` and :meth:`extend` rewrite the file and so
    require the caller to hold the relevant project lock.
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
        """Add one ``key`` to the window, evicting the oldest beyond ``capacity``."""

        self.extend((key,))

    def extend(self, keys: Iterable[str]) -> None:
        """Add ``keys`` to the window in order, then trim to the most recent ``capacity``.

        A batch keeps the trim to a single rewrite. An empty batch is a no-op —
        it neither creates nor rewrites the file.
        """

        additions = list(keys)
        if not additions:
            return

        # Append after the existing window, then keep only its most recent tail.
        window = self._load()
        window.extend(additions)
        write_atomic(self.path, "\n".join(window[-self.capacity :]) + "\n")

    def _load(self) -> list[str]:
        """The current window as an ordered list (oldest first); [] when absent."""

        if not self.path.exists():
            return []
        return self.path.read_text(encoding="utf-8").split()
