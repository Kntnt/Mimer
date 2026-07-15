"""Tests for the leakage guard (ADR 0027, issue #65): a fact the judgment rules
classify as sensitive waits, project-bound, for the user's consent before it is
ever promoted to global scope.

The guard is the moment distillation would promote a fact to global scope. A
sensitive fact — one carrying a clear confidentiality signal — is held at project
scope instead, with a consent request queued for the next session start; every
other fact is promoted as before, announced and reversible. Because the held fact
stays project-scoped, it never travels: the safe state is also the waiting state.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from pathlib import Path

import pytest

import mimer.distill as distill_module
from mimer.bundle import list_concepts, read_concept
from mimer.capture import capture_from_payload
from mimer.curate import remember
from mimer.distill import distill_durable_entries, distill_fact
from mimer.index import reindex, search
from mimer.leakage import (
    is_sensitive,
    pending_consent_requests,
    queue_consent_request,
    resolve_consent_request,
)
from mimer.recall import recall
from mimer.store import ensure_store
from tests.harness import run_hook, session_start_payload
from tests.transcript_fixture import write_transcript

# The recall, search and hook-subprocess paths load the embedding model, so the
# session fixture prefetches it once before the suite runs (conftest.py).
pytestmark = pytest.mark.embedding


@pytest.mark.parametrize(
    "text",
    [
        "This pricing arrangement is confidential.",
        "The engagement details are confidential to the client.",
        "The parties are bound by an NDA.",
        "The work is covered by a non-disclosure agreement.",
    ],
)
def test_default_classifier_flags_explicit_confidentiality_signals(text: str) -> None:
    """The default classifier flags a clear confidentiality or secret signal —
    the tight default the editable rules will later drive (ADR 0018, #70)."""

    assert is_sensitive(text)


@pytest.mark.parametrize(
    "text",
    [
        "The deploy day is Friday.",
        "Review the sprint agenda tomorrow.",
        "Filling in the form is mandatory.",
        "The client is Acme Corp; contact is hi@acme.example.",
    ],
)
def test_default_classifier_admits_non_sensitive_facts(text: str) -> None:
    """A plain fact carries no confidentiality signal and is not sensitive.

    The axis is "is this confidential?", not "is this about a client?": a bare
    client name or email is not auto-sensitive, and the ``nda`` signal is matched
    on a word boundary so ``agenda`` and ``mandatory`` never trip it."""

    assert not is_sensitive(text)


def test_sensitive_fact_bound_for_global_is_held_at_project_scope(store_root: Path) -> None:
    """A sensitive fact whose distillation would promote it to global is held at
    project scope instead of being promoted (ADR 0027)."""

    ensure_store(store_root)
    result = distill_fact(
        text="This pricing model is confidential to the client.",
        project_id="p",
        scope="global",
        root=store_root,
    )

    assert result.status == "created"
    assert result.held is True
    assert result.slug is not None
    concept = read_concept(result.slug, store_root)
    assert concept.scope == "project"


def test_held_fact_queues_a_consent_request(store_root: Path) -> None:
    """Holding a sensitive fact queues a consent request for the next session
    start, so the user is asked before it may ever go global (ADR 0027)."""

    ensure_store(store_root)
    distill_fact(
        text="The merger discussion is strictly confidential.",
        project_id="p",
        scope="global",
        root=store_root,
    )

    requests = pending_consent_requests("p", store_root)
    assert any("merger" in request.lower() for request in requests)


def test_distill_fact_attended_holds_sensitive_without_deferring_consent(store_root: Path) -> None:
    """With the user present ("distill now"), consent is resolved in the moment: with
    deferral off, distill_fact still holds a sensitive fact at project scope but
    queues NO consent request for the next session start (ADRs 0023, 0027, #69).

    This is the seam that keeps "distill now" from the one failure it must avoid —
    silently deferring a sensitive consent to the next session instead of resolving
    it while the user is there to answer."""

    ensure_store(store_root)
    result = distill_fact(
        text="The merger discussion is strictly confidential.",
        project_id="p",
        scope="global",
        root=store_root,
        defer_consent=False,
    )

    assert result.held is True
    assert result.slug is not None
    assert read_concept(result.slug, store_root).scope == "project"
    assert pending_consent_requests("p", store_root) == []


def test_resolve_consent_request_clears_only_the_answered_request(store_root: Path) -> None:
    """Answering one held fact's consent retires exactly its request and leaves any
    other held fact's request still pending, so the session-start prompt stops
    re-posing the answered fact but keeps asking about the rest (ADR 0027, #69)."""

    ensure_store(store_root)
    queue_consent_request("p", "The merger terms", store_root)
    queue_consent_request("p", "The pricing model", store_root)
    assert pending_consent_requests("p", store_root) == ["The merger terms", "The pricing model"]

    resolve_consent_request("p", "The merger terms", store_root)

    assert pending_consent_requests("p", store_root) == ["The pricing model"]


def test_resolve_consent_request_is_a_noop_when_nothing_was_queued(store_root: Path) -> None:
    """The attended "distill now" path queues no consent request, so clearing one on
    a promote from that path — or any never-queued fact — is a silent no-op, never an
    error (#69)."""

    ensure_store(store_root)

    resolve_consent_request("p", "never queued", store_root)

    assert pending_consent_requests("p", store_root) == []


def test_distill_durable_entries_attended_holds_without_deferring_consent(
    store_root: Path, resolve_project: Callable[[Path], str], project_dir: Path
) -> None:
    """A durable "remember this" entry that is sensitive, distilled on demand with
    the user present, is held at project scope but NOT queued for a next-session
    consent ask — the in-the-moment resolution "distill now" relies on (#69)."""

    ensure_store(store_root)
    pid = resolve_project(project_dir)
    remember("The client's pricing model is confidential.", project_id=pid, root=store_root)

    results = distill_durable_entries(pid, root=store_root, scope="global", attended=True)

    held = [result for result in results if result.held]
    assert held and held[0].slug is not None
    assert read_concept(held[0].slug, store_root).scope == "project"
    assert pending_consent_requests(pid, store_root) == []


def test_non_sensitive_fact_bound_for_global_is_promoted_and_announced(store_root: Path) -> None:
    """A non-sensitive fact is still promoted to global scope, announced and
    reversible — the 0%-effort common case is untouched (ADR 0027).

    No consent is requested for it: only sensitive content waits."""

    ensure_store(store_root)
    result = distill_fact(
        text="The team prefers dependency injection for testable seams.",
        project_id="p",
        scope="global",
        root=store_root,
    )

    assert result.held is False
    assert result.slug is not None
    concept = read_concept(result.slug, store_root)
    assert concept.scope == "global"
    # It is announced (the announce-and-undo path) and asks for no consent.
    announced = distill_module._peek_announcements("p", root=store_root)
    assert any("dependency injection" in title.lower() for title in announced)
    assert pending_consent_requests("p", store_root) == []


def _capture_payload(cwd: Path, transcript: Path) -> dict[str, object]:
    """A Stop-hook payload driving capture over a transcript from ``cwd``."""

    return {
        "session_id": "s",
        "hook_event_name": "Stop",
        "stop_hook_active": False,
        "cwd": str(cwd),
        "transcript_path": str(transcript),
    }


def test_held_fact_gates_the_concept_channel_but_the_captured_log_stays_widenable(
    store_root: Path, project_dir: Path, resolve_project: Callable[[Path], str]
) -> None:
    """The leakage guard gates the PROMOTION channel, not the raw log (ADR 0027).

    Exercised through the real production path — a Stop-hook capture into the daily
    log, then reindex — not a direct distillation. The earlier AC #2 test masked
    the leak by only distilling a project-scoped Concept and never writing the log
    chunk capture writes, so it never touched the widenable channel the guard does
    not cover (integration-review finding).

    Two truths hold together. The held fact's *Concept* stays project-scoped, so no
    global Concept carrying it reaches another project's widened recall — the
    promotion channel is gated. But the confidential utterance it was distilled
    from is captured verbatim into its origin project's daily log at capture time,
    and that raw log is reachable by another project's ``--widen`` recall by ADR
    0013's design: the content already travelled via the log before distillation
    ran, and redaction strips shape-detectable secrets, not confidential prose. The
    guarantee is on the promotion channel, not a claim the captured wording is
    unreachable across projects. Driving the guard with ``scope="global"`` here
    matches the sibling tests; the production promotion trigger lands with #70."""

    ensure_store(store_root)
    confidential = "The alpha engagement terms are confidential: fee is 2M with the client."

    # Capture the confidential utterance into alpha's daily log the way production
    # does — the Stop hook's extractive, redacted append — so the widenable
    # long-term log chunk actually exists before recall runs.
    alpha = resolve_project(project_dir)
    transcript = write_transcript(
        project_dir / "t.jsonl",
        [("record the engagement terms", confidential, "2026-07-11T10:00:00Z")],
    )
    capture_from_payload(_capture_payload(project_dir, transcript), root=store_root)

    # Distil the same fact bound for global: the guard holds it at project scope,
    # so the Concept — the promotion channel — never travels.
    held = distill_fact(text=confidential, project_id=alpha, scope="global", root=store_root)
    reindex(store_root)

    assert held.held is True
    assert held.slug is not None
    assert read_concept(held.slug, store_root).scope == "project"

    # Recallable in its own origin project (held, not lost).
    assert search("confidential engagement terms", root=store_root, project_id=alpha)

    from_beta = recall(
        "confidential engagement terms", root=store_root, project_id="beta", widen=True
    )

    # Promotion channel gated: the held Concept stayed project-scoped, so no
    # permanent-memory (Concept) chunk carrying it surfaces in beta's recall.
    concept_hits = [c for c in from_beta.citations if c.source.startswith("permanent/")]
    assert all("confidential" not in c.text.lower() for c in concept_hits)

    # Raw-log caveat (ADR 0013): the captured utterance IS reachable via the
    # widenable daily log — it travelled at capture time, which the guard does not
    # suppress. This is the honest cross-project behaviour the earlier test masked.
    log_hits = [c for c in from_beta.citations if c.source.startswith("long-term/")]
    assert any("confidential" in c.text.lower() for c in log_hits)


def test_held_sensitive_fact_never_supersedes_a_global_concept(store_root: Path) -> None:
    """A held, project-scoped sensitive fact must never supersede — and so narrow
    — a broader global Concept about the same subject (ADR 0027, issue #29).

    Narrowing a global Concept would drop it from recall in every other project:
    the cardinal store-wide leak the guard must not open in reverse."""

    ensure_store(store_root)
    distill_fact(text="Deploy day is Friday.", project_id="alpha", scope="global", root=store_root)
    result = distill_fact(
        text="Deploy day is confidential Monday.",
        project_id="alpha",
        scope="global",
        root=store_root,
    )
    reindex(store_root)

    assert result.held is True
    assert result.status != "superseded"
    active = [concept for concept in list_concepts(store_root) if concept.status == "active"]
    assert any(concept.scope == "global" and "Friday" in concept.body for concept in active)
    # The untouched global Concept still reaches an unrelated project.
    hits = search("which day do we deploy", root=store_root, project_id="beta")
    assert any("Friday" in citation.text for citation in hits)


def test_consent_queue_persists_across_peeks(store_root: Path) -> None:
    """Peeking the consent queue never clears it: the ask persists, session after
    session, until the user actually answers it (ADR 0027)."""

    ensure_store(store_root)
    queue_consent_request("p", "Confidential pricing model", store_root)

    first = pending_consent_requests("p", store_root)
    second = pending_consent_requests("p", store_root)
    assert first == ["Confidential pricing model"]
    assert second == first


def test_session_start_surfaces_pending_consent_request(
    store_root: Path, project_dir: Path, resolve_project: Callable[[Path], str]
) -> None:
    """The queued consent request is posed at the next session start, so a held
    fact's promotion decision reaches the user rather than sitting silent."""

    pid = resolve_project(project_dir)
    ensure_store(store_root)
    distill_fact(
        text="The client's revenue figures are confidential.",
        project_id=pid,
        scope="global",
        root=store_root,
    )

    result = run_hook(
        "SessionStart",
        session_start_payload(cwd=str(project_dir)),
        store_root=store_root,
        cwd=project_dir,
    )

    assert result.returncode == 0, result.stderr
    payload = _injected_context(result.stdout)
    assert "consent" in payload.lower()
    assert "revenue figures" in payload.lower()


def test_distillation_entry_point_carries_no_bootstrap_seeding_parameters() -> None:
    """The distillation entry point no longer carries the bootstrap-only seeding
    parameters (issue #65, completing #60).

    ``pinned``/``confirmed``/``concept_type`` were added together only so bootstrap
    could seed the pinned profile through ``distill_fact`` (#21). With bootstrap
    gone (ADR 0026), a distilled fact is always a project- or global-scoped Fact,
    so none of the three belong on the entry point any longer."""

    params = inspect.signature(distill_fact).parameters
    for gone in ("concept_type", "pinned", "confirmed"):
        assert gone not in params, gone


def _injected_context(stdout: str) -> str:
    """Extract the injected additionalContext from a SessionStart hook's stdout."""

    import json

    payload = json.loads(stdout)
    hook_output = payload["hookSpecificOutput"]
    assert hook_output["hookEventName"] == "SessionStart"
    return str(hook_output["additionalContext"])
