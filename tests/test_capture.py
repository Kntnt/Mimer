"""Tests for Stop-hook capture (Stage 3a): extractive, idempotent, redacted
appends to the daily long-term log, detached so the session is never delayed
(ADRs 0009, 0011, 0012).
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from mimer.capture import capture_from_payload
from mimer.failure_log import NON_FATAL_PREFIX, fresh_failures
from mimer.index import index_db_path, reindex
from mimer.longterm import (
    CAPTURE_LEDGER_FILENAME,
    daily_log_path,
    is_captured,
    long_term_dir,
    record_captured,
)
from mimer.paths import LOG_FILENAME
from mimer.project import resolve
from mimer.store import ensure_store
from tests.harness import run_hook
from tests.secret_samples import SAMPLES, Sample
from tests.transcript_fixture import write_transcript

# Every test here loads the embedding model (directly or via a hook subprocess),
# so the session fixture prefetches it once before the suite runs (conftest.py).
pytestmark = pytest.mark.embedding


def _payload(cwd: Path, transcript: Path) -> dict[str, object]:
    return {
        "session_id": "test-session",
        "hook_event_name": "Stop",
        "stop_hook_active": False,
        "cwd": str(cwd),
        "transcript_path": str(transcript),
    }


def _project_id(store_root: Path, cwd: Path) -> str:
    resolution = resolve(cwd, root=store_root)
    assert resolution.project_id is not None
    return resolution.project_id


def test_same_turn_captured_twice_lands_once(store_root: Path, project_dir: Path) -> None:
    """A double-fired capture of one turn is idempotent via the durable ledger."""

    ensure_store(store_root)
    transcript = write_transcript(
        project_dir / "t.jsonl", [("what next?", "ship the parser", "2026-07-11T10:00:00Z")]
    )
    payload = _payload(project_dir, transcript)

    first = capture_from_payload(payload, root=store_root)
    second = capture_from_payload(payload, root=store_root)

    assert first.status == "captured"
    assert second.status == "duplicate"
    pid = _project_id(store_root, project_dir)
    log = daily_log_path(pid, "2026-07-11", store_root).read_text()
    assert log.count("ship the parser") == 1


def test_identical_turns_at_different_moments_are_both_captured(
    store_root: Path, project_dir: Path
) -> None:
    """Two turns with identical text but different timestamps are both recorded;
    content-only identity would have discarded the second as a duplicate (#38)."""

    ensure_store(store_root)
    early = write_transcript(
        project_dir / "early.jsonl", [("continue", "Done.", "2026-07-11T10:00:00Z")]
    )
    late = write_transcript(
        project_dir / "late.jsonl", [("continue", "Done.", "2026-07-11T11:00:00Z")]
    )

    first = capture_from_payload(_payload(project_dir, early), root=store_root)
    second = capture_from_payload(_payload(project_dir, late), root=store_root)

    assert first.status == "captured"
    assert second.status == "captured"
    assert first.turn_id != second.turn_id
    pid = _project_id(store_root, project_dir)
    log = daily_log_path(pid, "2026-07-11", store_root).read_text()
    assert log.count("- Assistant: Done.") == 2


def test_seeded_secret_never_reaches_the_daily_log(store_root: Path, project_dir: Path) -> None:
    """A secret in the exchange is redacted before it is stored."""

    ensure_store(store_root)
    secret = "postgres://admin:s3cr3tPassw0rd@db.example.com:5432/prod"
    transcript = write_transcript(
        project_dir / "t.jsonl",
        [(f"connect with {secret}", "done, connected", "2026-07-11T10:00:00Z")],
    )

    capture_from_payload(_payload(project_dir, transcript), root=store_root)

    pid = _project_id(store_root, project_dir)
    log = daily_log_path(pid, "2026-07-11", store_root).read_text()
    assert "s3cr3tPassw0rd" not in log
    assert "REDACTED" in log


@pytest.mark.parametrize("sample", SAMPLES, ids=lambda s: s.name)
def test_broadened_secret_class_never_reaches_the_daily_log(
    store_root: Path, project_dir: Path, sample: Sample
) -> None:
    """Each broadened secret class is redacted before it lands in the daily log."""

    ensure_store(store_root)
    transcript = write_transcript(
        project_dir / "t.jsonl",
        [(f"here is {sample.text} thanks", "noted", "2026-07-11T10:00:00Z")],
    )

    capture_from_payload(_payload(project_dir, transcript), root=store_root)

    pid = _project_id(store_root, project_dir)
    log = daily_log_path(pid, "2026-07-11", store_root).read_text()
    assert sample.sensitive not in log


def test_broadened_secret_classes_never_reach_the_index(
    store_root: Path, project_dir: Path
) -> None:
    """No broadened secret class survives into the derived recall index.

    The index is built from the already-redacted daily logs, so capturing each
    class and reindexing must leave every sensitive value absent from index.db.
    """

    ensure_store(store_root)
    for offset, sample in enumerate(SAMPLES):
        transcript = write_transcript(
            project_dir / f"s{offset}.jsonl",
            [(f"here is {sample.text} thanks", "noted", f"2026-07-11T10:{offset:02d}:00Z")],
        )
        capture_from_payload(_payload(project_dir, transcript), root=store_root)

    reindex(store_root)

    indexed = index_db_path(store_root).read_bytes()
    for sample in SAMPLES:
        assert sample.sensitive.encode() not in indexed, sample.name


def test_turn_near_midnight_lands_in_its_own_day(store_root: Path, project_dir: Path) -> None:
    """Day assignment follows the turn's timestamp, not wall-clock now."""

    ensure_store(store_root)
    late = write_transcript(
        project_dir / "late.jsonl", [("late", "before midnight", "2026-07-11T23:59:00Z")]
    )
    early = write_transcript(
        project_dir / "early.jsonl", [("early", "after midnight", "2026-07-12T00:01:00Z")]
    )

    capture_from_payload(_payload(project_dir, late), root=store_root)
    capture_from_payload(_payload(project_dir, early), root=store_root)

    pid = _project_id(store_root, project_dir)
    assert "before midnight" in daily_log_path(pid, "2026-07-11", store_root).read_text()
    assert "after midnight" in daily_log_path(pid, "2026-07-12", store_root).read_text()
    assert "after midnight" not in daily_log_path(pid, "2026-07-11", store_root).read_text()


def test_capture_failure_is_logged_and_loses_nothing(store_root: Path, project_dir: Path) -> None:
    """A failing capture writes one failure line and keeps prior entries intact."""

    ensure_store(store_root)
    good = write_transcript(
        project_dir / "good.jsonl", [("q", "a good prior entry", "2026-07-11T10:00:00Z")]
    )
    capture_from_payload(_payload(project_dir, good), root=store_root)

    # A transcript path that is a directory forces a read error inside capture.
    broken_dir = project_dir / "not-a-file"
    broken_dir.mkdir()
    result = capture_from_payload(_payload(project_dir, broken_dir), root=store_root)

    assert result.status == "failed"
    assert (store_root / "mimer.log").read_text().strip() != ""
    pid = _project_id(store_root, project_dir)
    assert "a good prior entry" in daily_log_path(pid, "2026-07-11", store_root).read_text()


def test_corrupt_spool_is_logged_not_silent(
    store_root: Path, project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A corrupt spool file produces a failure-log line rather than vanishing.

    capture.main runs detached with stderr routed to DEVNULL, so a read or parse
    error on the spooled payload that escaped uncaught would leave no trace at
    all, breaking the module's "every failure is logged" contract (#40)."""

    import mimer.capture as capture_module

    ensure_store(store_root)
    monkeypatch.setenv("MIMER_HOME", str(store_root))
    spool = project_dir / "payload.json"
    spool.write_text("{ this is not valid json", encoding="utf-8")

    result = capture_module.main([str(spool)])

    assert result == 0
    assert (store_root / "mimer.log").read_text(encoding="utf-8").strip() != ""
    assert not spool.exists()


def test_index_contention_does_not_fail_a_durable_capture(
    store_root: Path, project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Benign index contention after a durable append never flips an already
    recorded capture to "failed": the daily-log entry stands and the index —
    derived and rebuildable (ADR 0011) — is simply retried on the next write.

    A concurrent writer hitting the index's busy timeout is contention, not a
    capture failure, so it must not raise a spurious session-start health warning
    either — yet it stays observable in the log itself (#40)."""

    import sqlite3

    import mimer.capture as capture_module

    ensure_store(store_root)
    transcript = write_transcript(
        project_dir / "t.jsonl", [("q", "a durable answer", "2026-07-11T10:00:00Z")]
    )

    def busy(*_: object, **__: object) -> None:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(capture_module, "index_if_present", busy)

    result = capture_from_payload(_payload(project_dir, transcript), root=store_root)

    assert result.status == "captured"
    pid = _project_id(store_root, project_dir)
    assert "a durable answer" in daily_log_path(pid, "2026-07-11", store_root).read_text()

    # The contention raises no session-start health warning, but is still logged
    # non-fatally so it stays observable via `mimer-manage health`.
    assert fresh_failures(store_root) == []
    assert NON_FATAL_PREFIX in (store_root / LOG_FILENAME).read_text(encoding="utf-8")


def test_concurrent_captures_lose_nothing(store_root: Path, project_dir: Path) -> None:
    """Concurrent captures of distinct turns all land (uses the store I/O layer)."""

    ensure_store(store_root)
    count = 10
    transcripts = [
        write_transcript(
            project_dir / f"t{i}.jsonl",
            [(f"question {i}", f"answer number {i}", "2026-07-11T10:00:00Z")],
        )
        for i in range(count)
    ]

    def capture(index: int) -> None:
        capture_from_payload(_payload(project_dir, transcripts[index]), root=store_root)

    threads = [threading.Thread(target=capture, args=(i,)) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    pid = _project_id(store_root, project_dir)
    log = daily_log_path(pid, "2026-07-11", store_root).read_text()
    for i in range(count):
        assert f"answer number {i}" in log


def test_capture_ledger_stays_bounded_over_many_turns(store_root: Path, project_dir: Path) -> None:
    """The capture ledger holds a bounded window, not one id per turn forever —
    yet a recently captured turn still dedups, so idempotency holds (#41)."""

    ensure_store(store_root)
    pid = _project_id(store_root, project_dir)

    # Record far more turns than any bounded window could hold.
    total = 4000
    for i in range(total):
        record_captured(pid, f"turn-{i:08d}", store_root)

    # The ledger is read in full on every capture, so its line count is the
    # per-write cost — it must stay well below one line per turn.
    ledger = long_term_dir(pid, store_root) / CAPTURE_LEDGER_FILENAME
    line_count = len(ledger.read_text().split())
    assert line_count <= 2000, f"capture ledger grew to {line_count} lines over {total} turns"

    # A recently recorded turn still re-fires as a duplicate (idempotency holds).
    assert is_captured(pid, f"turn-{total - 1:08d}", store_root)


def test_stop_hook_is_detached_and_eventually_captures(store_root: Path, project_dir: Path) -> None:
    """The Stop hook returns promptly and capture completes in the background."""

    ensure_store(store_root)
    transcript = write_transcript(
        project_dir / "t.jsonl", [("hello", "captured in the background", "2026-07-11T10:00:00Z")]
    )

    start = time.monotonic()
    result = run_hook(
        "Stop", _payload(project_dir, transcript), store_root=store_root, cwd=project_dir
    )
    elapsed = time.monotonic() - start

    assert result.returncode == 0, result.stderr
    assert elapsed < 5.0, f"hook blocked for {elapsed:.2f}s — capture was not detached"

    pid = _project_id(store_root, project_dir)
    log = daily_log_path(pid, "2026-07-11", store_root)
    deadline = time.time() + 15
    while time.time() < deadline:
        if log.exists() and "captured in the background" in log.read_text():
            break
        time.sleep(0.05)
    assert log.exists() and "captured in the background" in log.read_text()
