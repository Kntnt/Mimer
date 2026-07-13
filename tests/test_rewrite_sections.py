"""Tests for ``rewrite_sections`` — short-term memory's one locked writer (#51).

Every mutation of short-term memory funnels through this locked read-modify-write:
it takes the per-project lock, parses the sections, applies a caller transform
(sections in, sections out), renders and writes atomically. The concurrency test
is the regression guard the deleted ``storeio.update_file`` used to carry — the
lock is what stops two writers losing each other's update.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from mimer.shortterm import (
    Entry,
    parse_short_term,
    read_short_term,
    rewrite_sections,
    short_term_path,
)
from mimer.store import ensure_store


def test_rewrite_sections_persists_the_transformed_sections(store_root: Path) -> None:
    """The transform's returned sections are rendered and written back verbatim."""

    ensure_store(store_root)

    def add_note(sections: dict[str, list[Entry]]) -> dict[str, list[Entry]]:
        sections["Notes"].append(Entry("2026-07-11", "a curated note", durable=True))
        return sections

    rewrite_sections("proj", add_note, root=store_root)

    notes = parse_short_term(read_short_term("proj", store_root))["Notes"]
    assert [(entry.text, entry.durable) for entry in notes] == [("a curated note", True)]


def test_rewrite_sections_treats_a_missing_file_as_empty(store_root: Path) -> None:
    """With no short-term file yet, the transform receives every section empty and
    its result becomes the project's first short-term memory."""

    ensure_store(store_root)
    seen: dict[str, list[Entry]] = {}

    def capture(sections: dict[str, list[Entry]]) -> dict[str, list[Entry]]:
        seen.update({name: list(entries) for name, entries in sections.items()})
        sections["Notes"].append(Entry("2026-07-11", "first note"))
        return sections

    rewrite_sections("proj", capture, root=store_root)

    assert seen == {"Active threads": [], "Pending decisions": [], "Notes": []}
    assert short_term_path("proj", store_root).exists()


def test_rewrite_sections_serialises_concurrent_writers(store_root: Path) -> None:
    """Many concurrent locked read-modify-writes to one project's short-term memory
    all survive: the per-project lock serialises them with no lost update."""

    ensure_store(store_root)
    texts = [f"note-{i}" for i in range(15)]

    def add(text: str) -> None:
        def transform(sections: dict[str, list[Entry]]) -> dict[str, list[Entry]]:
            # Widen the read-modify-write window so an unlocked implementation
            # would reliably lose updates — proving the lock is what protects them.
            time.sleep(0.01)
            sections["Notes"].append(Entry("2026-07-11", text))
            return sections

        rewrite_sections("proj", transform, root=store_root)

    threads = [threading.Thread(target=add, args=(text,)) for text in texts]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    notes = parse_short_term(read_short_term("proj", store_root))["Notes"]
    assert {entry.text for entry in notes} == set(texts)
