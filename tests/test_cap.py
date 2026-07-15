"""Tests for the cap trigger (ADR 0017, issue #28): an over-cap write drives
distillation. Durable entries are *promoted* into permanent Concepts before
anything is evicted (promote-then-evict), and only then are transient entries
aged out verbatim into the daily log under an aged-out heading. Neither path
ever loses a word: a promoted entry lives on as a Concept, an aged-out one in
the daily log.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest

from mimer.bundle import list_concepts
from mimer.curate import remember
from mimer.leakage import pending_consent_requests
from mimer.longterm import daily_log_path
from mimer.registry import Registry
from mimer.shortterm import parse_short_term, read_short_term
from mimer.store import ensure_store


def _total(store_root: Path, pid: str) -> int:
    sections = parse_short_term(read_short_term(pid, store_root))
    return sum(len(entries) for entries in sections.values())


def test_over_cap_evicts_oldest_transient_to_daily_log(
    store_root: Path, resolve_project: Callable[[Path], str], project_dir: Path
) -> None:
    """An over-cap write ages out the oldest transient entry verbatim into the
    daily log under the aged-out heading, keeping short-term at the cap."""

    pid = resolve_project(project_dir)
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


def test_over_cap_durables_are_promoted_to_permanent(
    store_root: Path, resolve_project: Callable[[Path], str], project_dir: Path
) -> None:
    """When only durable entries remain, an over-cap write promotes them into
    permanent Concepts rather than warning and keeping them — the cap is the
    engine that feeds distillation (ADR 0017, issue #28)."""

    pid = resolve_project(project_dir)
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


def test_cap_overflow_promotes_non_sensitive_durable_to_global_scope(
    store_root: Path, resolve_project: Callable[[Path], str], project_dir: Path
) -> None:
    """A cap-overflow that promotes a non-sensitive durable "remember this" entry
    lands a GLOBAL-scoped Concept, so the fact travels across the practitioner's
    projects — the same global-gated path the session boundary and "distill now"
    take (ADRs 0013, 0017, 0027). The cap-overflow safety valve must not disagree
    with its sibling promotion paths by minting a project-scoped Concept that could
    never travel cross-project."""

    ensure_store(store_root)
    pid = resolve_project(project_dir)

    # The project's distill-to-global switch must be on for global scope to be
    # honoured (ADR 0013). It is the default; set here so the test's intent is
    # explicit and independent of that default.
    registry = Registry.load(store_root)
    registry.set_distill_to_global(pid, enabled=True)
    registry.save()

    # Two durable entries at cap=1: the second write pushes short-term over the cap
    # and drives the promotion of both.
    remember(
        "the client prefers British English spelling",
        project_id=pid,
        root=store_root,
        cap=1,
        durable=True,
        today=date(2026, 7, 1),
    )
    result = remember(
        "deployments run on Tuesday afternoons",
        project_id=pid,
        root=store_root,
        cap=1,
        durable=True,
        today=date(2026, 7, 2),
    )

    # The over-cap write promoted the durable entries, and every resulting Concept
    # is global-scoped — not the project scope the unscoped call would have minted.
    assert result.promoted
    concepts = list_concepts(store_root)
    assert concepts
    assert all(concept.scope == "global" for concept in concepts)


def test_cap_overflow_holds_sensitive_durable_at_project_scope_with_consent_queued(
    store_root: Path, resolve_project: Callable[[Path], str], project_dir: Path
) -> None:
    """A cap-overflow that promotes a SENSITIVE durable entry holds it at project
    scope and queues a consent request for the next session start — it never leaks
    to global (ADR 0027). The cap-overflow path is unattended (it fires during
    capture, no user present), so a sensitive cap-evicted fact routes through the
    SAME global-gated leakage guard the automatic boundary pass uses: held, not
    leaked, with the consent deferred to session start."""

    ensure_store(store_root)
    pid = resolve_project(project_dir)
    registry = Registry.load(store_root)
    registry.set_distill_to_global(pid, enabled=True)
    registry.save()

    # A benign filler plus a clearly-confidential fact at cap=1: the second write
    # goes over the cap and drives promotion of both.
    remember(
        "the API rate limit is one hundred requests per minute",
        project_id=pid,
        root=store_root,
        cap=1,
        durable=True,
        today=date(2026, 7, 1),
    )
    remember(
        "This pricing arrangement is confidential.",
        project_id=pid,
        root=store_root,
        cap=1,
        durable=True,
        today=date(2026, 7, 2),
    )

    # The sensitive fact is held at project scope, never promoted to global...
    concepts = list_concepts(store_root)
    confidential = next(concept for concept in concepts if "confidential" in concept.body.lower())
    assert confidential.scope == "project"

    # ...and its consent request is queued for the next session start, the
    # unattended-path deferral the automatic boundary pass also performs.
    requests = pending_consent_requests(pid, store_root)
    assert any("confidential" in request.lower() for request in requests)


def test_over_cap_write_promotes_durables_before_evicting(
    store_root: Path, resolve_project: Callable[[Path], str], project_dir: Path
) -> None:
    """Promote-then-evict: an over-cap write promotes the durable entry first, and
    the room that frees keeps the transient entries in place — none is aged out
    (issue #28). Evict-first would have dropped the oldest transient and left the
    durable stranded with a warning."""

    pid = resolve_project(project_dir)
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


def test_eviction_loses_nothing(
    store_root: Path, resolve_project: Callable[[Path], str], project_dir: Path
) -> None:
    """An evicted entry is present in the daily log and absent from short-term —
    never lost from both."""

    pid = resolve_project(project_dir)
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
    store_root: Path,
    resolve_project: Callable[[Path], str],
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed promotion is surfaced, never swallowed (ADR 0017): the durable
    entry stays over-cap in short-term and the write warns, rather than the entry
    being evicted on the strength of a promotion that never landed (issue #28)."""

    import mimer.distill as distill_module

    def boom(**_: object) -> None:
        raise RuntimeError("bundle write failed")

    monkeypatch.setattr(distill_module, "distill_fact", boom)

    pid = resolve_project(project_dir)
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
