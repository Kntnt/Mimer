"""Unit tests for the transcript adapter: extract the last exchange (capture) or
every exchange (bootstrap import) from a Claude Code transcript, tolerant of
string or block content.
"""

from __future__ import annotations

from pathlib import Path

from mimer.transcript import all_exchanges, last_exchange
from tests.transcript_fixture import write_transcript


def test_last_exchange_is_extracted(tmp_path: Path) -> None:
    """The adapter returns the final user/assistant pair with its date."""

    path = write_transcript(
        tmp_path / "t.jsonl",
        [
            ("first question", "first answer", "2026-07-10T09:00:00Z"),
            ("second question", "second answer", "2026-07-11T14:30:00Z"),
        ],
    )

    exchange = last_exchange(path)

    assert exchange is not None
    assert exchange.user_text == "second question"
    assert exchange.assistant_text == "second answer"
    assert exchange.date == "2026-07-11"


def test_turn_identity_is_stable_for_a_re_fired_turn(tmp_path: Path) -> None:
    """The same turn — identical text at the same timestamp — yields the same id
    across parses, so a re-fired identical Stop hook stays idempotent (#38)."""

    turns = [("q", "a", "2026-07-11T10:00:00Z")]
    first = last_exchange(write_transcript(tmp_path / "a.jsonl", turns))
    second = last_exchange(write_transcript(tmp_path / "b.jsonl", turns))

    assert first is not None and second is not None
    assert first.turn_id == second.turn_id


def test_same_text_at_different_moments_gets_distinct_identities(tmp_path: Path) -> None:
    """Identical text at two different timestamps yields distinct turn ids, so a
    genuinely repeated short exchange is not collapsed into one capture (#38)."""

    early = last_exchange(
        write_transcript(tmp_path / "e.jsonl", [("continue", "Done.", "2026-07-11T10:00:00Z")])
    )
    late = last_exchange(
        write_transcript(tmp_path / "l.jsonl", [("continue", "Done.", "2026-07-11T11:00:00Z")])
    )

    assert early is not None and late is not None
    assert early.turn_id != late.turn_id


def test_all_exchanges_gives_repeated_text_distinct_identities(tmp_path: Path) -> None:
    """Two same-text turns at different moments in one imported transcript get
    distinct turn ids, so bootstrap renders each as its own entry instead of
    collapsing the repeat onto the first turn's identity (#38)."""

    exchanges = all_exchanges(
        write_transcript(
            tmp_path / "t.jsonl",
            [
                ("continue", "Done.", "2026-07-11T10:00:00Z"),
                ("continue", "Done.", "2026-07-11T11:00:00Z"),
            ],
        )
    )

    assert len(exchanges) == 2
    assert exchanges[0].turn_id != exchanges[1].turn_id


def test_empty_transcript_returns_none(tmp_path: Path) -> None:
    """A transcript with no exchanges yields nothing to capture."""

    path = tmp_path / "empty.jsonl"
    path.write_text("", encoding="utf-8")

    assert last_exchange(path) is None
