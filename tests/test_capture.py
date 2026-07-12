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
from mimer.index import index_db_path, reindex
from mimer.longterm import daily_log_path
from mimer.project import resolve
from mimer.store import ensure_store
from tests.harness import run_hook
from tests.secret_samples import SAMPLES, Sample
from tests.transcript_fixture import write_transcript


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
