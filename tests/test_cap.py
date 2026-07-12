"""Tests for cap age-out (ADR 0017): an over-cap write evicts transient entries
verbatim into the daily log under an aged-out heading; durable entries are never
evicted at this stage; and the eviction never loses a word.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from mimer.curate import remember
from mimer.longterm import daily_log_path
from mimer.project import resolve
from mimer.shortterm import parse_short_term, read_short_term


def _project(store_root: Path, cwd: Path) -> str:
    resolution = resolve(cwd, root=store_root)
    assert resolution.project_id is not None
    return resolution.project_id


def _total(store_root: Path, pid: str) -> int:
    sections = parse_short_term(read_short_term(pid, store_root))
    return sum(len(entries) for entries in sections.values())


def test_over_cap_evicts_oldest_transient_to_daily_log(store_root: Path, project_dir: Path) -> None:
    """An over-cap write ages out the oldest transient entry verbatim into the
    daily log under the aged-out heading, keeping short-term at the cap."""

    pid = _project(store_root, project_dir)
    for index, day in enumerate(("2026-07-01", "2026-07-02", "2026-07-03")):
        remember(
            f"transient {index}",
            project_id=pid,
            root=store_root,
            cap=3,
            durable=False,
            today=date.fromisoformat(day),
        )

    result = remember(
        "the newest note",
        project_id=pid,
        root=store_root,
        cap=3,
        durable=False,
        today=date(2026, 7, 11),
    )

    assert _total(store_root, pid) == 3
    notes = parse_short_term(read_short_term(pid, store_root))["Notes"]
    assert not any("transient 0" in entry.text for entry in notes)
    assert result.aged_out
    log = daily_log_path(pid, "2026-07-11", store_root).read_text()
    assert "Aged out" in log
    assert "- [2026-07-01] transient 0" in log
    assert "aged out" in result.echo.lower()


def test_durable_entries_are_never_evicted(store_root: Path, project_dir: Path) -> None:
    """When only durable entries remain, an over-cap write warns and keeps all."""

    pid = _project(store_root, project_dir)
    for index in range(3):
        remember(
            f"durable {index}",
            project_id=pid,
            root=store_root,
            cap=3,
            durable=True,
            today=date(2026, 7, index + 1),
        )

    result = remember(
        "durable 3", project_id=pid, root=store_root, cap=3, durable=True, today=date(2026, 7, 11)
    )

    assert _total(store_root, pid) == 4
    assert result.warning is not None
    assert not result.aged_out


def test_mixed_evicts_transient_keeps_durable(store_root: Path, project_dir: Path) -> None:
    """Transient entries age out first; durable entries stay put."""

    pid = _project(store_root, project_dir)
    remember(
        "keep me forever",
        project_id=pid,
        root=store_root,
        cap=2,
        durable=True,
        today=date(2026, 7, 1),
    )
    remember(
        "throwaway one",
        project_id=pid,
        root=store_root,
        cap=2,
        durable=False,
        today=date(2026, 7, 2),
    )

    remember(
        "throwaway two",
        project_id=pid,
        root=store_root,
        cap=2,
        durable=False,
        today=date(2026, 7, 3),
    )

    sections = parse_short_term(read_short_term(pid, store_root))
    kept = [e.text for entries in sections.values() for e in entries]
    assert "keep me forever" in kept
    assert "throwaway one" not in kept
    assert (
        "- [2026-07-02] throwaway one" in daily_log_path(pid, "2026-07-03", store_root).read_text()
    )


def test_eviction_loses_nothing(store_root: Path, project_dir: Path) -> None:
    """An evicted entry is present in the daily log and absent from short-term —
    never lost from both."""

    pid = _project(store_root, project_dir)
    for index, day in enumerate(("2026-07-01", "2026-07-02")):
        remember(
            f"fact {index}",
            project_id=pid,
            root=store_root,
            cap=2,
            durable=False,
            today=date.fromisoformat(day),
        )

    remember(
        "fact 2", project_id=pid, root=store_root, cap=2, durable=False, today=date(2026, 7, 3)
    )

    short_term = read_short_term(pid, store_root)
    log = daily_log_path(pid, "2026-07-03", store_root).read_text()
    assert "fact 0" not in short_term
    assert "fact 0" in log
