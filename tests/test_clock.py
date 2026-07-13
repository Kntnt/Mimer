"""One clock (#37): capture, the session digest, and the snapshot's age labels
all key off a single UTC clock.

Capture derives a turn's day and time from its transcript timestamp; the digest
closes the session; the snapshot ages every dated entry. When these read
different zones, a single non-UTC session's captures and its digest can land in
different daily logs and read back in a jumbled order. These tests pin all three
to one clock with a fixture whose local (offset) date differs from its UTC date,
so the split-file bug cannot come back.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from mimer.capture import capture_from_payload
from mimer.digest import digest_session
from mimer.longterm import daily_log_path
from mimer.project import resolve
from mimer.shortterm import ensure_short_term, short_term_path
from mimer.store import ensure_store
from tests.transcript_fixture import write_transcript

# Capture and the digest drive index upkeep, which loads the embedding model, so
# the session prefetch must run before this suite (conftest.py).
pytestmark = pytest.mark.embedding

DIGEST_REPLY = """## Digest
We settled on a single UTC clock for capture and the digest.

## Active threads
- none

## Pending decisions
- none
"""


def _project_id(store_root: Path, cwd: Path) -> str:
    resolution = resolve(cwd, root=store_root)
    assert resolution.project_id is not None
    return resolution.project_id


def test_capture_and_digest_share_one_utc_day_across_the_boundary(
    store_root: Path, project_dir: Path
) -> None:
    """A turn whose local (offset) date is the day before its UTC date records
    both its extractive capture and its session digest to the single UTC-dated
    daily log — never split across the local day and the UTC day (#37).

    ``2026-07-11T23:30:00-05:00`` is ``2026-07-12T04:30:00Z``: local date the
    11th, UTC date the 12th. This is the boundary a non-UTC user hits every
    evening, and the digest runs with no injected day so it must derive its own
    from the same clock capture uses.
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
    digest = digest_session(payload, root=store_root, haiku=lambda _: DIGEST_REPLY)

    assert digest.status == "digested"
    pid = _project_id(store_root, project_dir)
    utc_log = daily_log_path(pid, utc_day, store_root).read_text()
    assert "one coherent session on UTC" in utc_log
    assert "## Session digest" in utc_log
    assert not daily_log_path(pid, local_day, store_root).exists()


def test_capture_time_label_reads_utc_not_the_offset(store_root: Path, project_dir: Path) -> None:
    """The extractive entry's time label is the turn's UTC wall clock, so it
    agrees with the day the entry is filed under (#37)."""

    ensure_store(store_root)
    transcript = write_transcript(
        project_dir / "t.jsonl",
        [("what time is it?", "recorded on the one clock", "2026-07-11T23:30:00-05:00")],
    )
    payload = {"cwd": str(project_dir), "transcript_path": str(transcript)}

    capture_from_payload(payload, root=store_root)

    pid = _project_id(store_root, project_dir)
    utc_log = daily_log_path(pid, "2026-07-12", store_root).read_text()
    assert "### 04:30 — turn" in utc_log


def test_age_labels_use_the_same_utc_clock(
    store_root: Path,
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

    pid = _project_id(store_root, project_dir)
    ensure_short_term(pid, store_root)
    short_term_path(pid, store_root).write_text(
        f"# Short-term memory — {pid}\n\n## Notes\n\n- [2026-07-12] fresh UTC-day note\n",
        encoding="utf-8",
    )

    session_start.handle({"cwd": str(project_dir), "source": "startup"})

    context = json.loads(capsys.readouterr().out)["hookSpecificOutput"]["additionalContext"]
    assert "[2026-07-12] (today)" in context
