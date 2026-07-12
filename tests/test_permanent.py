"""Tests for permanent memory (Stage 5a): the OKF bundle, Concept identity, the
pinned profile, curated-write routing, and scope-enforced recall over Concepts
(ADRs 0013, 0014, 0015; docs/okf-profile.md).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mimer.bundle import (
    PINNED_CAP,
    ConfirmationRequired,
    Source,
    concept_path,
    create_concept,
    index_md_path,
    list_concepts,
    read_concept,
    rename_concept,
)
from mimer.index import reindex, search
from mimer.project import resolve
from mimer.store import ensure_store
from tests.harness import run_hook, session_start_payload

OKF_SPEC = Path(__file__).resolve().parent.parent / "docs" / "okf" / "SPEC.md"


def test_okf_spec_is_vendored() -> None:
    """The pinned OKF spec is vendored under the docs."""

    assert OKF_SPEC.is_file()
    text = OKF_SPEC.read_text(encoding="utf-8")
    assert "Open Knowledge Format" in text
    assert "0.1" in text


def test_concept_round_trips_valid(store_root: Path) -> None:
    """A Concept round-trips against the OKF profile and appears in the index."""

    ensure_store(store_root)
    concept = create_concept(
        title="Prefer British English",
        body="The user prefers British English spelling in prose.",
        concept_type="Preference",
        origin="proj-a",
        scope="global",
        citations=[Source("long-term/2026-07-01.md", "prefers British English", "2026-07-01")],
        root=store_root,
    )

    loaded = read_concept(concept.slug, root=store_root)
    assert loaded.id == concept.id
    assert loaded.type == "Preference"
    assert loaded.origin == "proj-a"
    assert loaded.scope == "global"
    assert loaded.citations and loaded.citations[0].excerpt == "prefers British English"

    # The raw file has OKF-conformant frontmatter (a non-empty type) and citations.
    raw = concept_path(concept.slug, store_root).read_text(encoding="utf-8")
    assert raw.startswith("---")
    assert "type: Preference" in raw
    assert "# Citations" in raw
    # The bundle index lists the concept with its headline.
    assert concept.title in index_md_path(store_root).read_text(encoding="utf-8")


def test_curated_write_records_origin_and_scope(store_root: Path) -> None:
    """A curated write routed to permanent memory records origin and scope."""

    ensure_store(store_root)
    concept = create_concept(
        title="Deploy on Fridays",
        body="Releases go out on Fridays after standup.",
        concept_type="Decision",
        origin="proj-b",
        scope="project",
        root=store_root,
    )

    assert concept.origin == "proj-b"
    assert concept.scope == "project"


def test_citation_secret_is_redacted_before_the_concept_is_persisted(store_root: Path) -> None:
    """A secret in a citation — a credential-in-URL source or a secret-bearing
    excerpt — is stripped at the Concept-creation sink, so no caller can land one
    in the persisted file (issue #23)."""

    ensure_store(store_root)
    secret = "AKIA" + "IOSFODNN7" + "EXAMPLE"
    concept = create_concept(
        title="Deploy runbook",
        body="The deploy runbook lives in the ops repo.",
        concept_type="Reference",
        origin="proj-a",
        scope="global",
        citations=[
            Source(f"https://user:{secret}@example.com/runbook", f"token {secret}", "2026-07-01")
        ],
        root=store_root,
    )

    raw = concept_path(concept.slug, store_root).read_text(encoding="utf-8")
    assert secret not in raw
    loaded = read_concept(concept.slug, root=store_root)
    assert loaded.citations
    assert all(secret not in c.source and secret not in c.excerpt for c in loaded.citations)


def test_description_secret_is_redacted_at_the_sink(store_root: Path) -> None:
    """A secret in the description field is stripped before the Concept is persisted,
    and the surrounding text survives (issue #23)."""

    ensure_store(store_root)
    secret = "AKIA" + "IOSFODNN7" + "EXAMPLE"
    concept = create_concept(
        title="Access note",
        body="An access note.",
        concept_type="Reference",
        origin="proj-a",
        scope="global",
        description=f"summary mentioning {secret}",
        root=store_root,
    )

    loaded = read_concept(concept.slug, root=store_root)
    assert secret not in loaded.description
    assert secret not in concept_path(concept.slug, store_root).read_text(encoding="utf-8")
    assert "summary mentioning" in loaded.description


def test_pinned_write_without_confirmation_is_refused(store_root: Path) -> None:
    """A pinned/profile write without explicit confirmation is refused."""

    ensure_store(store_root)
    with pytest.raises(ConfirmationRequired):
        create_concept(
            title="Always greet warmly",
            body="Greet the user warmly at the start of each session.",
            concept_type="Preference",
            origin="proj-a",
            scope="global",
            pinned=True,
            confirmed=False,
            root=store_root,
        )


def test_pinned_cap_enforced_with_demotion(store_root: Path) -> None:
    """Pinning past the cap demotes the oldest pinned Concept; identity is kept."""

    ensure_store(store_root)
    pinned_ids = []
    for index in range(PINNED_CAP + 1):
        concept = create_concept(
            title=f"Profile fact {index}",
            body=f"Durable profile fact number {index}.",
            concept_type="Preference",
            origin="proj-a",
            scope="global",
            pinned=True,
            confirmed=True,
            timestamp=f"2026-07-{index + 1:02d}T00:00:00Z",
            root=store_root,
        )
        pinned_ids.append(concept.id)

    pinned_now = [c for c in list_concepts(store_root) if c.pinned]
    assert len(pinned_now) == PINNED_CAP
    # The oldest pinned was demoted, not deleted — its id survives.
    demoted = read_concept("profile-fact-0", root=store_root)
    assert demoted.pinned is False
    assert demoted.id == pinned_ids[0]


def test_rename_rewrites_links_index_and_search(store_root: Path) -> None:
    """A rename rewrites inbound links, regenerates the index and updates search
    — all keeping the Concept's identity."""

    ensure_store(store_root)
    target = create_concept(
        title="Old name",
        body="A concept others link to.",
        concept_type="Reference",
        origin="proj-a",
        scope="global",
        root=store_root,
    )
    create_concept(
        title="Linker",
        body=f"See [the target](/{target.slug}.md) for details.",
        concept_type="Reference",
        origin="proj-a",
        scope="global",
        root=store_root,
    )
    reindex(store_root)

    renamed = rename_concept(target.slug, "new-name", root=store_root)

    assert renamed.id == target.id
    assert not concept_path("old-name", store_root).exists()
    linker = read_concept("linker", root=store_root)
    assert "/new-name.md" in linker.body
    assert "/old-name.md" not in linker.body
    assert "new-name" in index_md_path(store_root).read_text(encoding="utf-8")
    results = search("concept others link to", root=store_root, project_id="proj-a")
    assert any(c.source.endswith("new-name.md") for c in results)


def test_concept_scope_is_enforced_in_search(store_root: Path) -> None:
    """A global Concept recalls cross-project; a project-scoped one stays home."""

    ensure_store(store_root)
    create_concept(
        title="Global technique",
        body="Prefer dependency injection for testable seams.",
        concept_type="Technique",
        origin="proj-a",
        scope="global",
        root=store_root,
    )
    create_concept(
        title="Client secret rule",
        body="The alpha client's API base path is internal-only.",
        concept_type="Decision",
        origin="proj-a",
        scope="project",
        root=store_root,
    )
    reindex(store_root)

    from_b_global = search("dependency injection seams", root=store_root, project_id="proj-b")
    from_b_scoped = search("client API base path", root=store_root, project_id="proj-b")

    assert any("dependency injection" in c.text for c in from_b_global)
    assert all("internal-only" not in c.text for c in from_b_scoped)


def test_snapshot_carries_profile_and_headlines(store_root: Path, project_dir: Path) -> None:
    """The snapshot now injects the pinned profile and Concept headlines."""

    ensure_store(store_root)
    resolution = resolve(project_dir, root=store_root)
    assert resolution.project_id is not None
    create_concept(
        title="User is Thomas",
        body="The user is Thomas, who prefers concise answers.",
        concept_type="Preference",
        origin=resolution.project_id,
        scope="global",
        pinned=True,
        confirmed=True,
        root=store_root,
    )
    create_concept(
        title="Uses sqlite-vec",
        body="Mimer indexes with sqlite-vec.",
        concept_type="Reference",
        origin=resolution.project_id,
        scope="global",
        root=store_root,
    )

    result = run_hook(
        "SessionStart",
        session_start_payload(cwd=str(project_dir)),
        store_root=store_root,
        cwd=project_dir,
    )

    context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "prefers concise answers" in context
    assert "Uses sqlite-vec" in context
