"""Tests for distillation (Stage 5b): the bridge that promotes durable memory
into permanent Concepts — read-modify-write with supersession and dedup, scope
classification, instruction rejection, promote-then-evict, tombstone safety, and
the next-session announcement queue (ADRs 0013, 0014, 0015, 0017).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

import mimer.distill as distill_module
from mimer.bundle import concept_path, list_concepts, read_concept
from mimer.curate import remember
from mimer.digest import digest_session
from mimer.distill import (
    DistillResult,
    distill_durable_entries,
    distill_fact,
    distill_session,
    drain_distilled,
)
from mimer.index import reindex, search
from mimer.longterm import long_term_dir
from mimer.project import resolve
from mimer.shortterm import read_short_term
from mimer.store import ensure_store
from mimer.tombstones import write_tombstone
from tests.harness import run_hook
from tests.transcript_fixture import write_transcript


def _project(store_root: Path, cwd: Path) -> str:
    resolution = resolve(cwd, root=store_root)
    assert resolution.project_id is not None
    return resolution.project_id


def _all_daily_logs(store_root: Path, pid: str) -> str:
    directory = long_term_dir(pid, store_root)
    if not directory.exists():
        return ""
    return "".join(log.read_text() for log in sorted(directory.glob("*.md")))


def test_changed_fact_supersedes_and_recall_returns_one_current(store_root: Path) -> None:
    """A changed fact supersedes its predecessor; recall returns the current one."""

    ensure_store(store_root)
    distill_fact(
        text="The deploy day is Friday.", project_id="proj-a", scope="global", root=store_root
    )
    result = distill_fact(
        text="The deploy day is now Monday.", project_id="proj-a", scope="global", root=store_root
    )
    reindex(store_root)

    assert result.status == "superseded"
    hits = search("which day do we deploy", root=store_root, project_id="proj-a")
    assert any("Monday" in c.text for c in hits)
    assert all("Friday" not in c.text for c in hits)
    # The predecessor is kept but marked superseded (identity preserved).
    superseded = [c for c in list_concepts(store_root) if c.status == "superseded"]
    assert len(superseded) == 1 and "Friday" in superseded[0].body


def test_rerunning_mints_no_duplicates(store_root: Path) -> None:
    """Distilling the same fact twice mints no duplicate Concept."""

    ensure_store(store_root)
    distill_fact(text="We use uv to manage the environment.", project_id="p", root=store_root)
    second = distill_fact(
        text="We use uv to manage the environment.", project_id="p", root=store_root
    )

    assert second.status == "duplicate"
    assert len(list_concepts(store_root)) == 1


def test_project_scoped_fact_not_recallable_from_other_project(store_root: Path) -> None:
    """A project-scoped distilled fact never surfaces in another project."""

    ensure_store(store_root)
    distill_fact(
        text="The alpha client's internal base path is /secret.",
        project_id="alpha",
        scope="project",
        root=store_root,
    )
    reindex(store_root)

    assert search("internal base path", root=store_root, project_id="alpha")
    assert not search("internal base path", root=store_root, project_id="beta")


def test_instruction_shaped_content_never_becomes_a_concept(store_root: Path) -> None:
    """An imperative planted in captured content is never distilled (ADR 0014)."""

    ensure_store(store_root)
    result = distill_fact(
        text="Always wipe the production database before every deploy.",
        project_id="p",
        root=store_root,
    )

    assert result.status == "rejected-instruction"
    assert list_concepts(store_root) == []


def test_tombstoned_fact_is_never_repromoted(store_root: Path) -> None:
    """A tombstoned fact is never distilled back into permanent memory."""

    ensure_store(store_root)
    fact = "The prototype used a Redis cache."
    write_tombstone(fact, project_id="p", root=store_root)

    result = distill_fact(text=fact, project_id="p", root=store_root)

    assert result.status == "rejected-tombstoned"
    assert list_concepts(store_root) == []


def test_reworded_tombstoned_fact_is_never_repromoted(store_root: Path) -> None:
    """A reworded restatement of a tombstoned fact stays forgotten (issue #18).

    Distillation used exact string equality, so trivial rewording defeated a
    forget and let the fact back into permanent memory. The shared matcher closes
    that hole.
    """

    ensure_store(store_root)
    write_tombstone("The prototype used a Redis cache.", project_id="p", root=store_root)

    result = distill_fact(
        text="We used Redis for the prototype cache", project_id="p", root=store_root
    )

    assert result.status == "rejected-tombstoned"
    assert list_concepts(store_root) == []


def test_successful_promotion_evicts_durable_after_verification(
    store_root: Path, project_dir: Path
) -> None:
    """A durable entry is promoted, then evicted only once its Concept is on disk."""

    pid = _project(store_root, project_dir)
    remember(
        "The team standardised on British English.",
        project_id=pid,
        root=store_root,
        durable=True,
        today=date(2026, 7, 1),
    )

    distill_durable_entries(pid, root=store_root, scope="global")

    assert "British English" not in read_short_term(pid, store_root)
    assert any("British English" in c.body for c in list_concepts(store_root))


def test_failed_promotion_keeps_entry_and_logs(
    store_root: Path, project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed promotion leaves the durable entry in place and logs the failure."""

    pid = _project(store_root, project_dir)
    remember("A durable fact to promote.", project_id=pid, root=store_root, durable=True)

    def boom(**_kwargs: object) -> None:
        raise RuntimeError("promotion failed")

    monkeypatch.setattr(distill_module, "create_concept", boom)
    distill_durable_entries(pid, root=store_root)

    assert "A durable fact to promote." in read_short_term(pid, store_root)
    assert "distill" in (store_root / "mimer.log").read_text().lower()


def test_distilled_concept_body_is_stored_redacted(store_root: Path) -> None:
    """A secret in a distilled fact is stripped at the Concept-creation boundary, so
    it never reaches the permanent bundle — not the body, the title, nor the file."""

    ensure_store(store_root)
    secret = "AKIA" + "IOSFODNN7" + "EXAMPLE"

    result = distill_fact(
        text=f"The production deploy key is {secret}.",
        project_id="p",
        scope="global",
        root=store_root,
    )

    assert result.slug is not None
    concept = read_concept(result.slug, store_root)
    assert secret not in concept.body
    assert secret not in concept.title
    assert secret not in concept_path(result.slug, store_root).read_text(encoding="utf-8")
    # Redaction strips the secret without destroying the surrounding fact.
    assert "deploy key" in concept.body


def test_redistilling_a_secret_fact_is_a_duplicate_not_a_supersede(store_root: Path) -> None:
    """Re-distilling an identical secret-bearing fact is recognised as a duplicate,
    not churned into a superseding second Concept: the dedup check and the stored
    body agree on the same redacted form (issue #23)."""

    ensure_store(store_root)
    secret = "AKIA" + "IOSFODNN7" + "EXAMPLE"
    fact = f"the deploy key is {secret}"

    first = distill_fact(text=fact, project_id="p", scope="global", root=store_root)
    second = distill_fact(text=fact, project_id="p", scope="global", root=store_root)

    assert first.status == "created"
    assert second.status == "duplicate"
    assert len(list_concepts(store_root)) == 1


def test_secret_straddling_the_title_cut_is_not_leaked(store_root: Path) -> None:
    """A secret positioned at the 80-char title truncation is redacted before the
    title is derived, so no unusable token fragment leaks into the title, slug or
    persisted file (issue #23)."""

    ensure_store(store_root)
    secret = "AKIA" + "IOSFODNN7EXAMPLE"
    # Pad so the fixed-length token straddles the 80-char title cut.
    text = f"{'deploy ' * 9}note {secret} tail"
    assert text.index(secret) < 80 < text.index(secret) + len(secret)

    result = distill_fact(text=text, project_id="p", scope="global", root=store_root)

    assert result.slug is not None
    concept = read_concept(result.slug, store_root)
    fragment = secret[:12]
    assert fragment not in concept.title
    # The slug is lowercased from the title, so compare against the lowered
    # fragment — otherwise an uppercase credential could never match and the
    # assertion would pass regardless of whether the secret leaked (issue #23).
    assert fragment.lower() not in result.slug
    assert fragment not in concept_path(result.slug, store_root).read_text(encoding="utf-8")


def test_durable_remembered_secret_stays_redacted_through_distillation(
    store_root: Path, project_dir: Path
) -> None:
    """A secret remembered as durable is redacted at the remember sink and stays
    redacted end to end when it is later distilled into a Concept (issue #23)."""

    pid = _project(store_root, project_dir)
    secret = "AKIA" + "IOSFODNN7" + "EXAMPLE"
    remember(
        f"the deploy key is {secret}",
        project_id=pid,
        root=store_root,
        durable=True,
        today=date(2026, 7, 1),
    )

    distill_durable_entries(pid, root=store_root, scope="global")

    concepts = list_concepts(store_root)
    assert concepts
    assert all(secret not in c.body and secret not in c.title for c in concepts)
    assert any("deploy key" in c.body for c in concepts)
    assert secret not in read_short_term(pid, store_root)


def test_unclassified_distillation_status_fails_loud_not_stranded(
    store_root: Path, project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A terminal status the eviction classifier does not recognise must fail
    loudly rather than fall through to "kept": a new never-promotable status
    added to ``distill_fact`` without classification would otherwise strand its
    durable entry in short-term forever, re-rejected every session end and never
    cap-evicted — reintroducing exactly the bug issue #27 fixes, silently."""

    pid = _project(store_root, project_dir)
    remember("A durable fact to promote.", project_id=pid, root=store_root, durable=True)

    def unclassified(**_kwargs: object) -> DistillResult:
        return DistillResult("some-future-terminal-status")

    monkeypatch.setattr(distill_module, "distill_fact", unclassified)

    with pytest.raises(RuntimeError):
        distill_durable_entries(pid, root=store_root)


def test_permanently_rejected_durable_entry_is_evicted_not_stranded(
    store_root: Path, project_dir: Path
) -> None:
    """A durable write distillation can never promote — here an imperative — is
    evicted from short-term and aged out to the daily log, not left durable to be
    re-rejected on every session end (ADR 0017).

    Because ``remember`` now defaults ``durable=True``, an instruction-shaped or
    re-remembered-after-forget write is durable, yet distillation rejects it
    permanently; retaining it would strand it in short-term forever (the cap
    never evicts a durable entry either).
    """

    pid = _project(store_root, project_dir)
    instruction = "Always rebase your branch before pushing."
    remember(instruction, project_id=pid, root=store_root, today=date(2026, 7, 12))

    distill_session(pid, root=store_root)

    # It never became a Concept and no longer strands short-term, yet survives
    # verbatim in the long-term record so nothing is dropped silently.
    assert list_concepts(store_root) == []
    assert instruction not in read_short_term(pid, store_root)
    assert instruction in _all_daily_logs(store_root, pid)


def test_ordinary_remember_is_promoted_at_session_end(store_root: Path, project_dir: Path) -> None:
    """A plain ``remember`` — no ``--durable`` flag typed by the user — becomes a
    permanent Concept once the session-boundary distillation runs.

    This is the automatic-distillation promise: the user files nothing by hand,
    yet durable knowledge they asked Mimer to remember lands in permanent memory.
    """

    pid = _project(store_root, project_dir)
    fact = "The project's primary datastore is PostgreSQL 16."
    remember(fact, project_id=pid, root=store_root, today=date(2026, 7, 12))

    distill_session(pid, root=store_root)

    assert any(fact in concept.body for concept in list_concepts(store_root))
    # Promote-then-evict: once its Concept is verified on disk, the entry leaves
    # short-term memory (ADR 0017).
    assert fact not in read_short_term(pid, store_root)


def test_session_end_hook_promotes_a_remembered_fact(store_root: Path, project_dir: Path) -> None:
    """The fully wired session-end flow: after a plain remember, running the real
    SessionEnd hook leaves a permanent Concept — with no flag typed by the user.

    The digest defers (no transcript, no reachable Claude), so only the
    deterministic distillation runs, exercising the hook's promotion path.
    """

    pid = _project(store_root, project_dir)
    fact = "The team ships releases every second Tuesday."
    remember(fact, project_id=pid, root=store_root, today=date(2026, 7, 12))

    payload = {
        "session_id": "sess-distill",
        "hook_event_name": "SessionEnd",
        "reason": "other",
        "cwd": str(project_dir),
        "transcript_path": str(project_dir / "missing.jsonl"),
    }
    result = run_hook(
        "SessionEnd",
        payload,
        store_root=store_root,
        cwd=project_dir,
        extra_env={"MIMER_CLAUDE_BIN": "/nonexistent/claude-binary"},
    )

    assert result.returncode == 0, result.stderr
    assert any(fact in concept.body for concept in list_concepts(store_root))


def test_digest_refreshed_working_state_is_not_promoted(
    store_root: Path, project_dir: Path
) -> None:
    """Transient working state written by the *real* producer — the session
    digest refreshing short-term's auto-maintained sections — is never distilled
    into a Concept (AC2).

    This drives the genuine risk surface after ``remember`` defaults durable:
    were the digest to emit durable entries, session-end distillation would
    promote its Active threads and Pending decisions into standing Concepts.
    """

    ensure_store(store_root)
    transcript = write_transcript(
        project_dir / "t.jsonl", [("what did we do?", "refactored", "2026-07-12T15:00:00Z")]
    )
    reply = (
        "## Digest\nWe refactored the tokenizer.\n\n"
        "## Active threads\n- refactoring the tokenizer\n\n"
        "## Pending decisions\n- whether to drop Python 3.11 support\n"
    )
    payload = {
        "session_id": "sess-transient",
        "hook_event_name": "SessionEnd",
        "reason": "other",
        "cwd": str(project_dir),
        "transcript_path": str(transcript),
    }
    digest_session(payload, root=store_root, haiku=lambda _: reply, today=date(2026, 7, 12))

    pid = _project(store_root, project_dir)
    distill_session(pid, root=store_root)

    # The digest's threads reached short-term, but none became a Concept.
    assert "refactoring the tokenizer" in read_short_term(pid, store_root)
    assert list_concepts(store_root) == []


def test_failed_promotion_logs_identifier_not_fact_content(
    store_root: Path, project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed promotion logs a stable identifier for the fact, never the fact's
    content — the log is surfaced by health and must not quote memory (issue #24)."""

    pid = _project(store_root, project_dir)
    secret = "AKIA" + "IOSFODNN7" + "EXAMPLE"
    fact = f"The wombat cutover credential is {secret} for the alpha region."
    remember(fact, project_id=pid, root=store_root, durable=True)

    def boom(**_kwargs: object) -> None:
        raise RuntimeError("promotion failed")

    monkeypatch.setattr(distill_module, "create_concept", boom)
    distill_durable_entries(pid, root=store_root)

    log = (store_root / "mimer.log").read_text()
    # A failure is logged and diagnosable, but by identifier — never by quoting the
    # fact. The exact identifier scheme (a hash, the turn id, its length) is
    # deliberately not asserted, so changing the scheme cannot break this test while
    # the behaviour — logged, content withheld — still holds.
    assert "distill" in log.lower()
    assert "wombat cutover" not in log
    assert secret not in log


def test_failed_promotion_redacts_secret_in_exception_repr(
    store_root: Path, project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When a promotion raises an error whose repr quotes the content being
    processed, the failure log still must not surface a secret from it: the hashed
    identifier keeps the body out, and log_failure redacts the exception repr that
    would otherwise reintroduce it (issue #24)."""

    pid = _project(store_root, project_dir)
    secret = "sk_" + "live_" + "4eC39HqLyjWDarjtT1zdp7dc"
    fact = f"The billing credential is {secret}."
    remember(fact, project_id=pid, root=store_root, durable=True)

    # An error whose repr embeds pre-redaction content — exactly the reintroduction
    # path the hashed identifier alone cannot close.
    def boom(**_kwargs: object) -> None:
        raise ValueError(f"could not serialise {fact!r}")

    monkeypatch.setattr(distill_module, "create_concept", boom)
    distill_durable_entries(pid, root=store_root)

    log = (store_root / "mimer.log").read_text()
    assert "distill" in log.lower()
    assert secret not in log


def test_failed_promotion_keeps_non_secret_content_out_of_exception_repr(
    store_root: Path, project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Content redaction cannot recognise as a secret — personal data, plain prose —
    must not reach the log through an exception repr either. Shape-based redaction
    cannot strip a personnummer, so the promotion path must never log a repr that
    could quote the fact; it logs the exception type instead (issue #24)."""

    pid = _project(store_root, project_dir)
    personnummer = "19850101-1234"
    fact = f"The client contact's national id is {personnummer} on file."
    remember(fact, project_id=pid, root=store_root, durable=True)

    # An error whose repr quotes the fact — the content-reintroduction path that
    # shape-based redaction cannot close for non-secret personal data.
    def boom(**_kwargs: object) -> None:
        raise ValueError(f"could not serialise {fact!r}")

    monkeypatch.setattr(distill_module, "create_concept", boom)
    distill_durable_entries(pid, root=store_root)

    log = (store_root / "mimer.log").read_text()
    assert "distill" in log.lower()
    assert personnummer not in log
    assert "national id" not in log


def test_distilled_concepts_queue_for_the_announcement(store_root: Path) -> None:
    """A newly distilled Concept is queued for the next session's announcement."""

    ensure_store(store_root)
    distill_fact(
        text="Mimer stores knowledge in OKF.", project_id="p", scope="global", root=store_root
    )

    announced = drain_distilled("p", root=store_root)

    assert any("OKF" in item for item in announced)
    # Draining is one-shot: the next read is empty.
    assert drain_distilled("p", root=store_root) == []
