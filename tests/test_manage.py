"""Tests for the management surface (Stage 5c): scope-enforced recall over
permanent memory, profile enumeration, recent distillations, store health, and
retraction (ADRs 0012, 0013).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mimer.bundle import Source, create_concept, retract_concept
from mimer.failure_log import log_failure
from mimer.index import reindex, search
from mimer.manage import main, profile, recent_concepts, store_health
from mimer.store import ensure_store


def test_global_recalls_cross_project_project_scoped_does_not(store_root: Path) -> None:
    """A global Concept from A recalls, cited, from B; a project-scoped one does not."""

    ensure_store(store_root)
    create_concept(
        title="Prefer small PRs",
        body="Keep pull requests small and focused.",
        concept_type="Preference",
        origin="proj-a",
        scope="global",
        citations=[Source("long-term/2026-07-01.md", "small PRs", "2026-07-01")],
        root=store_root,
    )
    create_concept(
        title="Alpha secret path",
        body="The alpha client uses the /internal admin route.",
        concept_type="Decision",
        origin="proj-a",
        scope="project",
        root=store_root,
    )
    reindex(store_root)

    global_hits = search("keep pull requests small", root=store_root, project_id="proj-b")
    scoped_hits = search("internal admin route", root=store_root, project_id="proj-b")

    assert any("small and focused" in c.text for c in global_hits)
    assert global_hits[0].source.endswith(".md")  # cited
    assert all("/internal admin" not in c.text for c in scoped_hits)


def test_profile_enumeration_matches_pinned_with_citations(store_root: Path) -> None:
    """Profile enumeration returns exactly the pinned Concepts, with citations."""

    ensure_store(store_root)
    create_concept(
        title="User is Thomas",
        body="The user is Thomas.",
        concept_type="Preference",
        origin="p",
        scope="global",
        pinned=True,
        confirmed=True,
        citations=[Source("long-term/2026-07-01.md", "the user is Thomas", "2026-07-01")],
        root=store_root,
    )
    create_concept(
        title="Not pinned",
        body="A regular concept.",
        concept_type="Reference",
        origin="p",
        scope="global",
        root=store_root,
    )

    enumerated = profile(store_root)

    assert [c.title for c in enumerated] == ["User is Thomas"]
    assert enumerated[0].citations and enumerated[0].citations[0].excerpt == "the user is Thomas"


def test_recent_concepts_lists_newest_first_and_empty_before_any(store_root: Path) -> None:
    """Recent distillations list newest-first, and read empty before any exist."""

    ensure_store(store_root)
    assert recent_concepts(store_root) == []

    create_concept(
        title="Older",
        body="Older fact.",
        concept_type="Fact",
        origin="p",
        scope="global",
        timestamp="2026-07-01T00:00:00Z",
        root=store_root,
    )
    create_concept(
        title="Newer",
        body="Newer fact.",
        concept_type="Fact",
        origin="p",
        scope="global",
        timestamp="2026-07-10T00:00:00Z",
        root=store_root,
    )

    recent = recent_concepts(store_root)
    assert [c.title for c in recent] == ["Newer", "Older"]


def test_store_health_reports_counts_sizes_and_failures(store_root: Path) -> None:
    """Store health reports counts, sizes, timestamps and recent failures."""

    ensure_store(store_root)
    create_concept(
        title="A concept",
        body="Some knowledge.",
        concept_type="Fact",
        origin="p",
        scope="global",
        timestamp="2026-07-05T00:00:00Z",
        root=store_root,
    )
    log_failure("something went wrong in capture", root=store_root)

    report = store_health(store_root)

    assert report.concept_count == 1
    assert report.store_bytes > 0
    assert report.last_distillation == "2026-07-05T00:00:00Z"
    assert any("something went wrong" in line for line in report.recent_failures)


def test_retracted_concept_stops_surfacing(store_root: Path) -> None:
    """A retracted Concept stops surfacing in recall and in the injected profile."""

    ensure_store(store_root)
    concept = create_concept(
        title="Regrettable claim",
        body="An outdated claim about the deployment window.",
        concept_type="Fact",
        origin="p",
        scope="global",
        pinned=True,
        confirmed=True,
        root=store_root,
    )
    reindex(store_root)
    assert search("deployment window claim", root=store_root, project_id="p")

    retract_concept(concept.slug, root=store_root)

    assert not search("deployment window claim", root=store_root, project_id="p")
    assert concept.title not in [c.title for c in profile(store_root)]


def test_retract_cli_rejects_traversal_slug_with_clean_message(
    store_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``mimer-manage retract`` answers a traversal slug with a one-line rejection
    and a non-zero exit, never a raw traceback (#25)."""

    monkeypatch.setenv("MIMER_HOME", str(store_root))
    ensure_store(store_root)

    exit_code = main(["retract", "../evil"])

    assert exit_code != 0
    out = capsys.readouterr().out
    assert out.startswith("Mimer: invalid slug")
    assert "Traceback" not in out
