"""Tests for short-term memory parse/render round-tripping.

The durability flag is encoded out-of-band, so content that legitimately ends in
the literal marker text is never misparsed as durable nor has those words stripped
— content corruption plus a spurious durability flag the old trailing-substring
sniff produced (ADR 0017, #40).
"""

from __future__ import annotations

from pathlib import Path

from mimer.shortterm import (
    SHORT_TERM_FORMAT_MARKER,
    Entry,
    migrate_short_term_content,
    migrate_short_term_files,
    parse_short_term,
    render_short_term,
    short_term_path,
)
from mimer.store import ensure_store


def _round_trip(entry: Entry) -> Entry:
    """Render one entry and parse it back, returning the reconstructed entry."""

    sections: dict[str, list[Entry]] = {
        "Active threads": [],
        "Pending decisions": [],
        "Notes": [entry],
    }
    reparsed = parse_short_term(render_short_term("proj", sections))["Notes"]
    assert len(reparsed) == 1
    return reparsed[0]


def test_entry_ending_in_literal_durable_marker_round_trips() -> None:
    """A transient entry whose text legitimately ends in ``[durable]`` survives a
    render/parse round-trip verbatim, with no durability flag inferred."""

    entry = Entry("2026-07-11", "see the note tagged [durable]", durable=False)

    result = _round_trip(entry)

    assert result.text == "see the note tagged [durable]"
    assert result.durable is False


def test_durable_flag_round_trips_without_corrupting_text() -> None:
    """A durable entry round-trips with both its text and its flag intact."""

    entry = Entry("2026-07-11", "the client uses PostgreSQL", durable=True)

    result = _round_trip(entry)

    assert result.text == "the client uses PostgreSQL"
    assert result.durable is True


# A short-term file written by the pre-#40 code, where the durable marker was a
# trailing free-text suffix rather than the current structural slot.
_LEGACY_DOCUMENT = (
    "# Short-term memory — proj\n\n"
    "## Active threads\n\n"
    "## Pending decisions\n\n"
    "## Notes\n\n"
    "- [2026-07-11] the client uses PostgreSQL [durable]\n"
    "- [2026-07-11] a plain transient note\n"
)


def test_legacy_trailing_durable_marker_migrates_to_structural() -> None:
    """A pre-#40 durable line (trailing ``[durable]``) migrates to the structural
    format with its durability preserved and no ``[durable]`` left in its text —
    the silent loss the current parser alone would introduce (#40)."""

    migrated = migrate_short_term_content("proj", _LEGACY_DOCUMENT)

    notes = parse_short_term(migrated)["Notes"]
    durable = next(entry for entry in notes if entry.durable)
    assert durable.text == "the client uses PostgreSQL"
    assert "[durable]" not in durable.text
    assert any(entry.text == "a plain transient note" and not entry.durable for entry in notes)


def test_migration_preserves_a_legacy_durable_entry_and_is_gated(store_root: Path) -> None:
    """The one-time upgrade rewrites a legacy durable entry to the structural format,
    then never re-runs — so a later new-format transient whose text legitimately
    ends in ``[durable]`` is not re-sniffed as durable (#40)."""

    ensure_store(store_root)
    path = short_term_path("proj", store_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_LEGACY_DOCUMENT, encoding="utf-8")

    rewritten = migrate_short_term_files(store_root)

    assert rewritten == 1
    assert (store_root / SHORT_TERM_FORMAT_MARKER).exists()
    durable = next(e for e in parse_short_term(path.read_text())["Notes"] if e.durable)
    assert durable.text == "the client uses PostgreSQL"

    # A new-format transient whose text ends in the literal marker is written after
    # migration; the gate must stop the ambiguous rewrite from corrupting it.
    literal = Entry("2026-07-12", "see the note tagged [durable]", durable=False)
    path.write_text(
        render_short_term(
            "proj", {"Active threads": [], "Pending decisions": [], "Notes": [literal]}
        ),
        encoding="utf-8",
    )

    assert migrate_short_term_files(store_root) == 0
    preserved = parse_short_term(path.read_text())["Notes"]
    assert preserved == [literal]


def test_migration_leaves_an_already_migrated_durable_file_untouched(store_root: Path) -> None:
    """A crash mid-sweep leaves the marker unwritten, so a retry re-runs; a file
    already rewritten to the structural format must survive that retry intact
    rather than have its ``][durable]`` line re-parsed as legacy text (#40)."""

    ensure_store(store_root)
    path = short_term_path("proj", store_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = Entry("2026-07-11", "the client uses PostgreSQL", durable=True)
    path.write_text(
        render_short_term(
            "proj", {"Active threads": [], "Pending decisions": [], "Notes": [entry]}
        ),
        encoding="utf-8",
    )

    migrate_short_term_files(store_root)

    assert parse_short_term(path.read_text())["Notes"] == [entry]
