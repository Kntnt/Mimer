"""Unit tests for snapshot rendering: age labelling of dated entries and the
data-framed, announced injection payload (ADRs 0014, 0016).
"""

from __future__ import annotations

from datetime import date

from mimer.snapshot import (
    DATA_FRAME_HEADER,
    annotate_ages,
    build_snapshot,
    count_dated_items,
)

TODAY = date(2026, 7, 11)


def test_age_label_today_yesterday_and_days_ago() -> None:
    """Dated tokens are annotated with a human age relative to today."""

    text = "- [2026-07-11] a\n- [2026-07-10] b\n- [2026-06-20] c\n"

    annotated = annotate_ages(text, TODAY)

    assert "[2026-07-11] (today)" in annotated
    assert "[2026-07-10] (yesterday)" in annotated
    assert "[2026-06-20] (21 days ago)" in annotated


def test_count_dated_items() -> None:
    """Dated entries are counted for the announcement."""

    assert count_dated_items("- [2026-07-11] a\n- [2026-07-10] b\n") == 2
    assert count_dated_items("## Notes\n") == 0


def test_build_snapshot_frames_announces_and_labels() -> None:
    """The snapshot carries the data frame, a one-line announcement and ages."""

    text = "## Notes\n\n- [2026-06-20] shipped the parser\n"

    snapshot = build_snapshot("proj", text, today=TODAY, source="startup")

    assert DATA_FRAME_HEADER in snapshot
    assert 'Mimer: injected short-term memory for project "proj"' in snapshot
    assert "shipped the parser" in snapshot
    assert "(21 days ago)" in snapshot


def test_build_snapshot_empty_is_well_formed() -> None:
    """An empty short-term memory yields a well-formed 'nothing yet' snapshot."""

    empty = "# Short-term memory — proj\n\n## Active threads\n\n## Pending decisions\n\n## Notes\n"

    snapshot = build_snapshot("proj", empty, today=TODAY, source="startup")

    assert DATA_FRAME_HEADER in snapshot
    assert 'Mimer: no short-term memory yet for project "proj"' in snapshot
