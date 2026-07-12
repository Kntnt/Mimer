"""Unit tests for curated writes (Stage 2): remember adds and dedups, an
over-cap write warns but evicts nothing, and soft forget removes the entry and
writes a tombstone that keeps the fact gone (ADRs 0012, 0017, 0018).
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import date
from pathlib import Path

from mimer.curate import forget, remember
from mimer.project import resolve
from mimer.shortterm import parse_short_term, read_short_term
from mimer.tombstones import is_tombstoned, load_tombstones

TODAY = date(2026, 7, 11)


def _project(store_root: Path, cwd: Path) -> str:
    resolution = resolve(cwd, root=store_root)
    assert resolution.project_id is not None
    return resolution.project_id


def test_remember_adds_dated_entry_with_echo(store_root: Path, project_dir: Path) -> None:
    """Remembering a fact adds a dated entry and echoes what happened."""

    pid = _project(store_root, project_dir)

    result = remember("use sqlite-vec for the index", project_id=pid, root=store_root, today=TODAY)

    assert "remembered" in result.echo.lower()
    notes = parse_short_term(read_short_term(pid, store_root))["Notes"]
    assert len(notes) == 1
    assert notes[0].date == "2026-07-11"
    assert notes[0].text == "use sqlite-vec for the index"


def test_remember_duplicate_updates_not_duplicates(store_root: Path, project_dir: Path) -> None:
    """Re-remembering an existing fact updates it rather than duplicating."""

    pid = _project(store_root, project_dir)
    remember("prefer uv over pip", project_id=pid, root=store_root, today=date(2026, 7, 1))

    result = remember("prefer uv over pip", project_id=pid, root=store_root, today=TODAY)

    assert result.action == "updated"
    notes = parse_short_term(read_short_term(pid, store_root))["Notes"]
    assert len(notes) == 1
    assert notes[0].date == "2026-07-11"


def test_over_cap_durable_write_warns_and_evicts_nothing(
    store_root: Path, project_dir: Path
) -> None:
    """When only durable entries remain, an over-cap write warns and keeps all
    (durable entries are promoted by distillation, not aged out — ADR 0017)."""

    pid = _project(store_root, project_dir)
    for i in range(3):
        remember(f"fact {i}", project_id=pid, root=store_root, cap=3, durable=True, today=TODAY)

    result = remember(
        "one too many", project_id=pid, root=store_root, cap=3, durable=True, today=TODAY
    )

    assert result.warning is not None
    assert "cap" in result.warning.lower()
    assert not result.aged_out
    notes = parse_short_term(read_short_term(pid, store_root))["Notes"]
    assert len(notes) == 4


def test_forget_removes_entry_and_writes_tombstone(store_root: Path, project_dir: Path) -> None:
    """Soft forget removes the entry, tombstones it, and says the raw record
    stays."""

    pid = _project(store_root, project_dir)
    remember("the staging password is hunter2", project_id=pid, root=store_root, today=TODAY)

    result = forget("the staging password is hunter2", project_id=pid, root=store_root, today=TODAY)

    assert result.action == "removed"
    assert "tombstone" in result.echo.lower()
    assert "untouched" in result.echo.lower()
    notes = parse_short_term(read_short_term(pid, store_root))["Notes"]
    assert notes == []
    assert is_tombstoned("the staging password is hunter2", project_id=pid, root=store_root)


def test_tombstoned_fact_stays_gone_across_reload(store_root: Path, project_dir: Path) -> None:
    """A forgotten fact does not reappear in short-term memory on reload."""

    pid = _project(store_root, project_dir)
    remember("drop the old cache table", project_id=pid, root=store_root, today=TODAY)
    forget("drop the old cache table", project_id=pid, root=store_root, today=TODAY)

    reloaded = read_short_term(pid, store_root)

    assert "drop the old cache table" not in reloaded
    assert len(load_tombstones(store_root)) == 1


def test_remembered_secret_is_stored_redacted(store_root: Path, project_dir: Path) -> None:
    """A secret passed to remember is stripped before it lands in short-term memory
    (ADR-level guarantee: redaction is enforced at the sink, not by agent judgment)."""

    pid = _project(store_root, project_dir)
    secret = "AKIA" + "IOSFODNN7" + "EXAMPLE"

    remember(f"the deploy key is {secret}", project_id=pid, root=store_root, today=TODAY)

    stored = read_short_term(pid, store_root)
    assert secret not in stored
    assert "REDACTED" in stored
    # Redaction removes the secret without destroying the surrounding fact.
    assert "deploy key" in stored


def test_forget_by_the_full_secret_removes_the_redacted_entry(
    store_root: Path, project_dir: Path
) -> None:
    """Forgetting by the exact secret string still removes the entry that remember
    stored in redacted form, and no raw secret is persisted to the tombstone
    ledger (forget runs the same redacting sink as remember — issue #23)."""

    pid = _project(store_root, project_dir)
    secret = "AKIA" + "IOSFODNN7" + "EXAMPLE"
    remember(f"the deploy key is {secret}", project_id=pid, root=store_root, today=TODAY)

    result = forget(f"the deploy key is {secret}", project_id=pid, root=store_root, today=TODAY)

    assert result.action == "removed"
    assert parse_short_term(read_short_term(pid, store_root))["Notes"] == []
    tombstones = load_tombstones(store_root)
    assert tombstones and all(
        secret not in t["text"] and secret not in t["key"] for t in tombstones
    )


def test_remember_persists_for_a_new_session(store_root: Path, project_dir: Path) -> None:
    """A remembered fact is present when short-term memory is read afresh (the
    automated proxy for the manual restart residue)."""

    pid = _project(store_root, project_dir)
    remember("the client prefers British English", project_id=pid, root=store_root, today=TODAY)

    assert "the client prefers British English" in read_short_term(pid, store_root)


def test_cli_remember_writes_and_echoes(store_root: Path, project_dir: Path) -> None:
    """The ``mimer-memory`` CLI the skill drives writes to the resolved project
    and echoes the outcome."""

    executable = Path(sys.executable).parent / "mimer-memory"
    env = {**os.environ, "MIMER_HOME": str(store_root)}
    env.pop("MIMER_GUARD", None)

    result = subprocess.run(
        [str(executable), "remember", "the CLI path works end to end"],
        cwd=str(project_dir),
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "remembered" in result.stdout.lower()
    pid = _project(store_root, project_dir)
    assert "the CLI path works end to end" in read_short_term(pid, store_root)


def test_cli_note_stores_redacted(store_root: Path, project_dir: Path) -> None:
    """The ``note`` CLI verb runs the same redacting sink as remember, so a secret
    noted at the command line is stored redacted (AC1 names remember and note)."""

    executable = Path(sys.executable).parent / "mimer-memory"
    env = {**os.environ, "MIMER_HOME": str(store_root)}
    env.pop("MIMER_GUARD", None)
    secret = "AKIA" + "IOSFODNN7" + "EXAMPLE"

    result = subprocess.run(
        [str(executable), "note", f"the deploy key is {secret}"],
        cwd=str(project_dir),
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    pid = _project(store_root, project_dir)
    stored = read_short_term(pid, store_root)
    assert secret not in stored
    assert "deploy key" in stored
