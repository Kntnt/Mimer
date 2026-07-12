"""Tests for the cap trigger (ADR 0017, issue #28): an over-cap write drives
distillation. Durable entries are *promoted* into permanent Concepts before
anything is evicted (promote-then-evict), and only then are transient entries
aged out verbatim into the daily log under an aged-out heading. Neither path
ever loses a word: a promoted entry lives on as a Concept, an aged-out one in
the daily log.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from mimer.bundle import list_concepts
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


def test_over_cap_durables_are_promoted_to_permanent(store_root: Path, project_dir: Path) -> None:
    """When only durable entries remain, an over-cap write promotes them into
    permanent Concepts rather than warning and keeping them — the cap is the
    engine that feeds distillation (ADR 0017, issue #28)."""

    pid = _project(store_root, project_dir)
    facts = (
        "the client prefers British English spelling",
        "deployments run on Tuesday afternoons",
        "the API rate limit is one hundred requests per minute",
    )
    for index, fact in enumerate(facts):
        remember(
            fact,
            project_id=pid,
            root=store_root,
            cap=3,
            durable=True,
            today=date(2026, 7, index + 1),
        )

    result = remember(
        "the staging server runs Ubuntu",
        project_id=pid,
        root=store_root,
        cap=3,
        durable=True,
        today=date(2026, 7, 11),
    )

    # Every durable entry became a Concept and left short-term; nothing was aged
    # out (promotion, not eviction) and nothing warns (the cap was cleared).
    assert len(list_concepts(store_root)) == 4
    assert _total(store_root, pid) == 0
    assert result.warning is None
    assert not result.aged_out
    assert len(result.promoted) == 4


def test_over_cap_write_promotes_durables_before_evicting(
    store_root: Path, project_dir: Path
) -> None:
    """Promote-then-evict: an over-cap write promotes the durable entry first, and
    the room that frees keeps the transient entries in place — none is aged out
    (issue #28). Evict-first would have dropped the oldest transient and left the
    durable stranded with a warning."""

    pid = _project(store_root, project_dir)
    remember(
        "the client's database is PostgreSQL 16",
        project_id=pid,
        root=store_root,
        cap=2,
        durable=True,
        today=date(2026, 7, 1),
    )
    remember(
        "chase the flaky CI job later",
        project_id=pid,
        root=store_root,
        cap=2,
        durable=False,
        today=date(2026, 7, 2),
    )

    result = remember(
        "the meeting moved to Thursday",
        project_id=pid,
        root=store_root,
        cap=2,
        durable=False,
        today=date(2026, 7, 3),
    )

    # The durable fact is promoted out; both transient notes survive because the
    # promotion made room before eviction was ever considered.
    concepts = list_concepts(store_root)
    assert any("PostgreSQL" in concept.body for concept in concepts)
    short_term = read_short_term(pid, store_root)
    assert "PostgreSQL" not in short_term
    assert "chase the flaky CI job later" in short_term
    assert "the meeting moved to Thursday" in short_term
    assert not result.aged_out
    assert result.warning is None


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


def test_failed_durable_promotion_keeps_the_entry_and_warns(
    store_root: Path, project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed promotion is surfaced, never swallowed (ADR 0017): the durable
    entry stays over-cap in short-term and the write warns, rather than the entry
    being evicted on the strength of a promotion that never landed (issue #28)."""

    import mimer.distill as distill_module

    def boom(**_: object) -> None:
        raise RuntimeError("bundle write failed")

    monkeypatch.setattr(distill_module, "distill_fact", boom)

    pid = _project(store_root, project_dir)
    for index in range(3):
        remember(
            f"durable topic number {index}",
            project_id=pid,
            root=store_root,
            cap=3,
            durable=True,
            today=date(2026, 7, index + 1),
        )

    result = remember(
        "durable topic number three",
        project_id=pid,
        root=store_root,
        cap=3,
        durable=True,
        today=date(2026, 7, 11),
    )

    assert result.warning is not None
    assert _total(store_root, pid) == 4
    assert not list_concepts(store_root)
