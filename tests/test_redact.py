"""Tests for the hard "redact" forgetting tier (issue #31, ADR 0012).

Redact is a superset of forget: it removes the fact from short-term memory and
tombstones it (the soft tier), then additionally erases it from the raw record —
the append-only daily long-term logs and the archived transcripts — and rebuilds
the derived index so the purged content stops surfacing in recall. It also serves
the case where a secret slipped past the storage-time redaction pass.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest

from mimer.curate import _build_parser, forget, redact, remember
from mimer.index import reindex, search
from mimer.longterm import append_entry, daily_log_path, transcripts_dir
from mimer.shortterm import parse_short_term, read_short_term
from mimer.storeio import write_atomic
from mimer.tombstones import is_tombstoned, load_tombstones

TODAY = date(2026, 7, 11)


def _transcript_line(text: str, timestamp: str = "2026-07-11T10:00:00Z") -> str:
    """One well-formed transcript JSONL record carrying ``text``."""

    return json.dumps(
        {
            "type": "assistant",
            "timestamp": timestamp,
            "message": {"role": "assistant", "content": text},
        }
    )


def test_redact_removes_short_term_entry_and_writes_a_redact_tombstone(
    store_root: Path, resolve_project: Callable[[Path], str], project_dir: Path
) -> None:
    """Redact does everything forget does: the entry leaves short-term memory and a
    tombstone (tier ``redact``) is written so the fact never resurfaces."""

    pid = resolve_project(project_dir)
    remember("the office moves to the fourth floor", project_id=pid, root=store_root, today=TODAY)

    result = redact("the office moves to the fourth floor", project_id=pid, root=store_root)

    assert result.action == "redacted"
    assert parse_short_term(read_short_term(pid, store_root))["Notes"] == []
    assert is_tombstoned("the office moves to the fourth floor", project_id=pid, root=store_root)
    tombstones = load_tombstones(store_root)
    assert any(record["tier"] == "redact" for record in tombstones)


def test_redact_erases_the_fact_from_the_daily_log_in_place(
    store_root: Path, resolve_project: Callable[[Path], str], project_dir: Path
) -> None:
    """Redact rewrites the append-only daily log, replacing the fact's span with a
    redaction marker — the one sanctioned mutation of the raw record (ADR 0012)."""

    pid = resolve_project(project_dir)
    fact = "the office moves to the fourth floor in august"
    append_entry(
        pid, TODAY.isoformat(), f"### 10:00 — turn abcd1234\n- Assistant: {fact}\n", store_root
    )

    redact(fact, project_id=pid, root=store_root)

    log = daily_log_path(pid, TODAY.isoformat(), store_root).read_text(encoding="utf-8")
    assert "fourth floor" not in log
    assert "REDACTED" in log


def test_redact_is_surgical_and_keeps_unrelated_content_in_a_bundled_bullet(
    store_root: Path, resolve_project: Callable[[Path], str], project_dir: Path
) -> None:
    """When the fact is one span inside a larger captured bullet, only that span is
    replaced; the unrelated content in the same bullet survives."""

    pid = resolve_project(project_dir)
    fact = "the staging password is hunter2"
    bullet = f"- Assistant: session tokens live in Redis and {fact} until the next rotation.\n"
    append_entry(pid, TODAY.isoformat(), f"### 10:00 — turn abcd1234\n{bullet}", store_root)

    redact(fact, project_id=pid, root=store_root)

    log = daily_log_path(pid, TODAY.isoformat(), store_root).read_text(encoding="utf-8")
    assert "hunter2" not in log
    assert "session tokens live in Redis" in log
    assert "REDACTED" in log


def test_redact_erases_the_fact_from_the_transcript_archive_keeping_valid_json(
    store_root: Path, resolve_project: Callable[[Path], str], project_dir: Path
) -> None:
    """Redact rewrites the archived transcript in place, and the result is still a
    parseable JSONL record (the marker introduces no JSON-breaking characters)."""

    pid = resolve_project(project_dir)
    fact = "the office moves to the fourth floor in august"
    archive = transcripts_dir(pid, store_root) / "sess-1.jsonl"
    write_atomic(archive, _transcript_line(f"reminder: {fact}") + "\n")

    redact(fact, project_id=pid, root=store_root)

    text = archive.read_text(encoding="utf-8")
    assert "fourth floor" not in text
    assert "REDACTED" in text
    json.loads(text.strip())


def test_redact_erases_a_secret_that_slipped_past_the_storage_time_pass(
    store_root: Path, resolve_project: Callable[[Path], str], project_dir: Path
) -> None:
    """Redact scrubs a raw secret already sitting in the log, even though the
    tombstone ledger never records the raw secret (the erasure works on the raw
    text; the tombstone on the secret-stripped form — issue #23)."""

    pid = resolve_project(project_dir)
    secret = "AKIA" + "IOSFODNN7" + "EXAMPLE"
    append_entry(
        pid,
        TODAY.isoformat(),
        f"### 10:00 — turn abcd1234\n- Assistant: the deploy key is {secret} for now\n",
        store_root,
    )

    redact(f"the deploy key is {secret}", project_id=pid, root=store_root)

    log = daily_log_path(pid, TODAY.isoformat(), store_root).read_text(encoding="utf-8")
    assert secret not in log
    tombstones = load_tombstones(store_root)
    assert tombstones and all(secret not in record["text"] for record in tombstones)


def test_redact_echo_states_the_honest_residual(
    store_root: Path, resolve_project: Callable[[Path], str], project_dir: Path
) -> None:
    """The echo relayed to the user names the erasure and the honest residual:
    content exported or backed up before the redact is beyond Mimer's reach (AC4)."""

    pid = resolve_project(project_dir)
    remember("drop the temporary feature flag", project_id=pid, root=store_root, today=TODAY)

    echo = redact("drop the temporary feature flag", project_id=pid, root=store_root).echo.lower()

    assert "redacted" in echo
    assert "raw" in echo
    assert "export" in echo or "backed up" in echo


def test_forget_echo_references_only_a_real_command(
    store_root: Path, resolve_project: Callable[[Path], str], project_dir: Path
) -> None:
    """The forget echo must not point the user at a command that does not exist
    (AC3): if it mentions redact, redact must be a real ``mimer-memory`` subcommand."""

    pid = resolve_project(project_dir)
    remember("the retro is on thursday", project_id=pid, root=store_root, today=TODAY)

    result = forget("the retro is on thursday", project_id=pid, root=store_root)

    if "redact" in result.echo.lower():
        args = _build_parser().parse_args(["redact", "the retro is on thursday"])
        assert args.command == "redact"


def test_cli_redact_erases_across_layers(
    store_root: Path, resolve_project: Callable[[Path], str], project_dir: Path
) -> None:
    """The ``mimer-memory redact`` CLI the skill drives erases the fact and echoes
    the outcome, exit code zero."""

    pid = resolve_project(project_dir)
    fact = "the office moves to the fourth floor in august"
    append_entry(
        pid, TODAY.isoformat(), f"### 10:00 — turn abcd1234\n- Assistant: {fact}\n", store_root
    )

    executable = Path(sys.executable).parent / "mimer-memory"
    env = {**os.environ, "MIMER_HOME": str(store_root)}
    env.pop("MIMER_GUARD", None)

    result = subprocess.run(
        [str(executable), "redact", fact],
        cwd=str(project_dir),
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "redacted" in result.stdout.lower()
    log = daily_log_path(pid, TODAY.isoformat(), store_root).read_text(encoding="utf-8")
    assert "fourth floor" not in log


@pytest.mark.embedding
def test_redacted_fact_absent_from_recall_logs_and_transcript(
    store_root: Path, resolve_project: Callable[[Path], str], project_dir: Path
) -> None:
    """The full-erasure guarantee (AC2): after redact, the fact appears in neither
    recall, the daily logs, nor the transcript archive."""

    pid = resolve_project(project_dir)
    fact = "the legacy billing endpoint is /v1/charge"

    # A daily log carrying the fact, plus an archived transcript carrying it.
    log_path = daily_log_path(pid, "2026-06-01", store_root)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        f"## Billing\n\nThe team noted that {fact} and will remove it later.\n", encoding="utf-8"
    )
    archive = transcripts_dir(pid, store_root) / "sess-1.jsonl"
    write_atomic(archive, _transcript_line(f"reminder: {fact}", "2026-06-01T10:00:00Z") + "\n")

    reindex(store_root)
    assert search("what is the legacy billing endpoint?", root=store_root, project_id=pid)

    redact(fact, project_id=pid, root=store_root)

    results = search("what is the legacy billing endpoint?", root=store_root, project_id=pid)
    assert all("/v1/charge" not in citation.text for citation in results)
    assert "/v1/charge" not in log_path.read_text(encoding="utf-8")
    assert "/v1/charge" not in archive.read_text(encoding="utf-8")
