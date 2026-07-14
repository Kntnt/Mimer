"""One clock (#37): capture, the session-boundary pass, and the snapshot's age
labels all key off a single UTC clock.

Capture derives a turn's day and time from its transcript timestamp; the boundary
pass distils the day's raw record and refreshes short-term; the snapshot ages
every dated entry. When these read different zones, a single non-UTC session's
captures could land under a different day than the boundary pass reads, so the
pass would distil an empty record. These tests pin all three to one clock with a
fixture whose local (offset) date differs from its UTC date, so the split-day bug
cannot come back.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest

from mimer.boundary import run_boundary_pass
from mimer.capture import capture_from_payload
from mimer.longterm import daily_log_path
from mimer.shortterm import ensure_short_term, read_short_term, short_term_path
from mimer.store import ensure_store
from tests.transcript_fixture import write_transcript

# Capture and the boundary pass drive index upkeep, which loads the embedding
# model, so the session prefetch must run before this suite (conftest.py).
pytestmark = pytest.mark.embedding

BOUNDARY_REPLY = """## Active threads
- verifying the one-clock invariant

## Pending decisions
- none

## Durable facts
- none
"""


def test_capture_and_boundary_pass_share_one_utc_day_across_the_boundary(
    store_root: Path, resolve_project: Callable[[Path], str], project_dir: Path
) -> None:
    """A turn whose local (offset) date is the day before its UTC date is captured
    under the single UTC-dated daily log, and the boundary pass — running with no
    injected day — reads that same UTC-dated record and refreshes short-term under
    it, never splitting across the local day and the UTC day (#37).

    ``2026-07-11T23:30:00-05:00`` is ``2026-07-12T04:30:00Z``: local date the
    11th, UTC date the 12th. This is the boundary a non-UTC user hits every
    evening, and the pass must derive its own day from the same clock capture uses,
    or it would distil the empty local-day record instead of the real one.
    """

    ensure_store(store_root)
    timestamp = "2026-07-11T23:30:00-05:00"
    utc_day = "2026-07-12"
    local_day = "2026-07-11"
    transcript = write_transcript(
        project_dir / "t.jsonl",
        [("which clock do we use?", "one coherent session on UTC", timestamp)],
    )
    payload = {
        "session_id": "sess-clock",
        "cwd": str(project_dir),
        "transcript_path": str(transcript),
    }

    capture_from_payload(payload, root=store_root)
    seen: dict[str, str] = {}

    def stub(prompt: str) -> str:
        seen["prompt"] = prompt
        return BOUNDARY_REPLY

    result = run_boundary_pass(payload, root=store_root, haiku=stub)

    assert result.status == "completed"
    pid = resolve_project(project_dir)
    # The pass read the raw record filed under the UTC day, not the empty local day.
    assert "one coherent session on UTC" in seen["prompt"]
    # Its short-term refresh is dated on the same UTC day.
    assert "[2026-07-12] verifying the one-clock invariant" in read_short_term(pid, store_root)
    # Capture filed the turn under the UTC day, and nothing landed under the local day.
    assert "one coherent session on UTC" in daily_log_path(pid, utc_day, store_root).read_text()
    assert not daily_log_path(pid, local_day, store_root).exists()


def test_capture_time_label_reads_utc_not_the_offset(
    store_root: Path, resolve_project: Callable[[Path], str], project_dir: Path
) -> None:
    """The extractive entry's time label is the turn's UTC wall clock, so it
    agrees with the day the entry is filed under (#37)."""

    ensure_store(store_root)
    transcript = write_transcript(
        project_dir / "t.jsonl",
        [("what time is it?", "recorded on the one clock", "2026-07-11T23:30:00-05:00")],
    )
    payload = {"cwd": str(project_dir), "transcript_path": str(transcript)}

    capture_from_payload(payload, root=store_root)

    pid = resolve_project(project_dir)
    utc_log = daily_log_path(pid, "2026-07-12", store_root).read_text()
    assert "### 04:30 — turn" in utc_log


def test_age_labels_use_the_same_utc_clock(
    store_root: Path,
    resolve_project: Callable[[Path], str],
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The snapshot ages entries against the same UTC clock, so an entry stamped
    on the UTC day reads as ``today`` rather than shifted a day by a local
    wall-clock (#37)."""

    import mimer.clock as clock
    from mimer.hooks import session_start

    ensure_store(store_root)
    monkeypatch.setenv("MIMER_HOME", str(store_root))
    monkeypatch.setattr(clock, "today", lambda: date(2026, 7, 12))

    pid = resolve_project(project_dir)
    ensure_short_term(pid, store_root)
    short_term_path(pid, store_root).write_text(
        f"# Short-term memory — {pid}\n\n## Notes\n\n- [2026-07-12] fresh UTC-day note\n",
        encoding="utf-8",
    )

    session_start.handle({"cwd": str(project_dir), "source": "startup"})

    context = json.loads(capsys.readouterr().out)["hookSpecificOutput"]["additionalContext"]
    assert "[2026-07-12] (today)" in context
