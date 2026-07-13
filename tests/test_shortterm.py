"""Tests for short-term memory parse/render round-tripping.

The durability flag is encoded out-of-band, so content that legitimately ends in
the literal marker text is never misparsed as durable nor has those words stripped
— content corruption plus a spurious durability flag the old trailing-substring
sniff produced (ADR 0017, #40).
"""

from __future__ import annotations

from mimer.shortterm import Entry, parse_short_term, render_short_term


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
