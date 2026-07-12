"""Tests for permanent memory (Stage 5a): the OKF bundle, Concept identity, the
pinned profile, curated-write routing, and scope-enforced recall over Concepts
(ADRs 0013, 0014, 0015; docs/okf-profile.md).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import mimer.bundle as bundle
from mimer.bundle import (
    PINNED_CAP,
    Concept,
    ConfirmationRequired,
    Source,
    bundle_dir,
    concept_headlines,
    concept_path,
    create_concept,
    index_md_path,
    list_concepts,
    mark_superseded,
    read_concept,
    rename_concept,
    retract_concept,
)
from mimer.index import reindex, search
from mimer.manage import store_health
from mimer.paths import LOG_FILENAME
from mimer.project import resolve
from mimer.store import ensure_store
from tests.harness import run_hook, session_start_payload

OKF_SPEC = Path(__file__).resolve().parent.parent / "docs" / "okf" / "SPEC.md"


@pytest.fixture(autouse=True)
def _reset_bundle_skip_ledger(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give each test a fresh copy of the process-global skip-dedup ledger.

    ``bundle._LOGGED_SKIPS`` deduplicates the "skipped unparseable Concept" log
    line to once per process. Left un-reset it leaks across tests, so a later
    bad-file test that skips a file at a path an earlier test already skipped
    would find it pre-deduped and log zero new lines — making the load-bearing
    "logged exactly once" assertions pass or fail on test order rather than on
    the behaviour under test (issue #17).
    """

    monkeypatch.setattr(bundle, "_LOGGED_SKIPS", set(), raising=False)


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


def test_tag_secret_is_redacted_at_the_sink(store_root: Path) -> None:
    """A secret carried in a tag is stripped at the Concept-creation sink, so it
    never lands in the frontmatter, while a clean tag survives (issue #23)."""

    ensure_store(store_root)
    secret = "AKIA" + "IOSFODNN7" + "EXAMPLE"
    concept = create_concept(
        title="Tagged note",
        body="A note carrying a tagged secret.",
        concept_type="Reference",
        origin="proj-a",
        scope="global",
        tags=["deploy", f"key-{secret}"],
        root=store_root,
    )

    loaded = read_concept(concept.slug, root=store_root)
    assert all(secret not in tag for tag in loaded.tags)
    assert secret not in concept_path(concept.slug, store_root).read_text(encoding="utf-8")
    assert "deploy" in loaded.tags


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


def test_crash_between_temp_write_and_rename_preserves_previous(
    store_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fault injected between temp-write and rename leaves the previous Concept
    intact and readable — permanent memory is the one layer nothing can rebuild
    (issue #17)."""

    ensure_store(store_root)
    concept = create_concept(
        title="Durable fact",
        body="The one source of truth that must survive a crashed write.",
        concept_type="Reference",
        origin="proj-a",
        scope="global",
        root=store_root,
    )
    path = concept_path(concept.slug, store_root)
    original = path.read_text(encoding="utf-8")

    # Fault the atomic rename so any bundle write crashes with the temp file
    # written but the live file not yet replaced.
    def crash(_src: object, _dst: object) -> None:
        raise OSError("simulated crash before rename")

    monkeypatch.setattr(os, "replace", crash)

    with pytest.raises(OSError):
        mark_superseded(concept.slug, "01OTHERCONCEPTID0000000000", root=store_root)

    # The previous file is byte-for-byte intact and still parses.
    assert path.read_text(encoding="utf-8") == original
    reloaded = read_concept(concept.slug, root=store_root)
    assert reloaded.id == concept.id
    assert reloaded.status == "active"


def test_crash_during_index_regeneration_preserves_previous_index(
    store_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fault injected while regenerating index.md leaves the previous index
    byte-for-byte intact — the derived index is written through the same atomic
    helper as the source Concepts, so a crash mid-regenerate cannot tear it
    (issue #17)."""

    ensure_store(store_root)
    create_concept(
        title="First fact",
        body="The first durable fact, already indexed.",
        concept_type="Reference",
        origin="proj-a",
        scope="global",
        root=store_root,
    )
    index_path = index_md_path(store_root)
    original = index_path.read_text(encoding="utf-8")

    # Fault the atomic rename only for the index write, letting the Concept file
    # write succeed, so the crash lands squarely on index.md regeneration.
    real_replace = os.replace

    def crash_index_only(src: Path, dst: Path) -> None:
        if Path(dst).name == bundle.INDEX_FILENAME:
            raise OSError("simulated crash before index rename")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", crash_index_only)

    with pytest.raises(OSError):
        create_concept(
            title="Second fact",
            body="A second fact whose index regeneration crashes mid-write.",
            concept_type="Reference",
            origin="proj-a",
            scope="global",
            root=store_root,
        )

    # The previous index.md is byte-for-byte intact and still lists the first fact.
    assert index_path.read_text(encoding="utf-8") == original
    assert "First fact" in original


def _create_good_concept(store_root: Path) -> Concept:
    """Create one well-formed, parseable Concept in the bundle."""

    return create_concept(
        title="Valid concept",
        body="A well-formed, parseable Concept.",
        concept_type="Reference",
        origin="proj-a",
        scope="global",
        root=store_root,
    )


def _write_bad_concept(store_root: Path) -> None:
    """Drop a botched hand-edit — a Concept file with no frontmatter at all — into
    the bundle, the case that today bricks every reader (issue #17)."""

    (bundle_dir(store_root) / "broken.md").write_text(
        "just some prose, no frontmatter here\n", encoding="utf-8"
    )


# One unparseable Concept must degrade to "that file is skipped and logged", not
# "the whole bundle is unusable". Each reader that iterates the bundle is asserted
# on its own so a regression confined to any single surface is pinpointed, rather
# than masked behind whichever assertion happens to run first (issue #17).


def test_list_concepts_skips_one_bad_concept(store_root: Path) -> None:
    """list_concepts returns every valid Concept and drops the unparseable file,
    rather than letting the parse failure propagate to every caller (issue #17)."""

    ensure_store(store_root)
    good = _create_good_concept(store_root)
    _write_bad_concept(store_root)

    slugs = [concept.slug for concept in list_concepts(store_root)]
    assert good.slug in slugs
    assert "broken" not in slugs


def test_reindex_indexes_the_valid_concept_despite_one_bad_file(store_root: Path) -> None:
    """reindex not only survives the bad file but lands the valid Concept in the
    derived index: a post-reindex search finds it (issue #17)."""

    ensure_store(store_root)
    good = _create_good_concept(store_root)
    _write_bad_concept(store_root)

    reindex(store_root)

    hits = search("Valid concept parseable", root=store_root)
    assert any(hit.source == f"permanent/{good.slug}.md" for hit in hits)


def test_concept_headlines_survive_one_bad_file(store_root: Path) -> None:
    """The manifest's Concept headlines still list every valid Concept when one
    file in the bundle is unparseable (issue #17)."""

    ensure_store(store_root)
    _create_good_concept(store_root)
    _write_bad_concept(store_root)

    assert any("Valid concept" in headline for headline in concept_headlines(store_root))


def test_store_health_counts_only_the_valid_concepts(store_root: Path) -> None:
    """mimer-manage's health surface counts the valid Concepts and does not choke
    on an unparseable file (issue #17)."""

    ensure_store(store_root)
    _create_good_concept(store_root)
    _write_bad_concept(store_root)

    assert store_health(store_root).concept_count == 1


def test_one_bad_concept_is_logged_once_across_many_reads(store_root: Path) -> None:
    """A single unparseable Concept yields exactly one actionable log line however
    many readers iterate the bundle in a process — recall reindex, the manifest and
    the health surface all skip the same file without re-logging it (issue #17)."""

    ensure_store(store_root)
    _create_good_concept(store_root)
    _write_bad_concept(store_root)

    # Exercise every in-process reader that iterates the bundle, several times over.
    for _ in range(3):
        list_concepts(store_root)
    reindex(store_root)
    concept_headlines(store_root)
    store_health(store_root)

    log_lines = [
        line
        for line in (store_root / LOG_FILENAME).read_text(encoding="utf-8").splitlines()
        if "broken.md" in line
    ]
    assert len(log_lines) == 1
    assert "skipped" in log_lines[0].lower()


def test_concurrent_delete_is_skipped_but_not_logged_as_unparseable(
    store_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Concept unlinked by another process between enumeration and read is a
    concurrent delete, not corruption: it is skipped, every surviving Concept is
    still returned, and the log names the real cause instead of blaming an
    'unparseable' file that never was (issue #17, ADR 0011)."""

    ensure_store(store_root)
    survivor = _create_good_concept(store_root)
    vanishing = create_concept(
        title="Vanishing concept",
        body="A Concept another process unlinks mid-enumeration.",
        concept_type="Reference",
        origin="proj-a",
        scope="global",
        root=store_root,
    )

    # Simulate a detached writer unlinking one file after glob() but before this
    # process reads it, which surfaces as FileNotFoundError from read_concept.
    real_read = bundle.read_concept

    def read_or_vanish(slug: str, root: Path | None = None) -> Concept:
        if slug == vanishing.slug:
            raise FileNotFoundError(concept_path(slug, store_root))
        return real_read(slug, root)

    monkeypatch.setattr(bundle, "read_concept", read_or_vanish)

    slugs = [concept.slug for concept in list_concepts(store_root)]
    assert survivor.slug in slugs
    assert vanishing.slug not in slugs

    # The skip is logged, but as an unreadable file, never as unparseable content.
    log_line = next(
        line
        for line in (store_root / LOG_FILENAME).read_text(encoding="utf-8").splitlines()
        if f"{vanishing.slug}.md" in line
    )
    assert "skipped" in log_line.lower()
    assert "unparseable" not in log_line.lower()


def test_session_start_injects_valid_concept_despite_one_bad_file(
    store_root: Path, project_dir: Path
) -> None:
    """Session-start injection survives one bad Concept file: the valid Concept is
    still injected instead of the session getting no memory at all (issue #17)."""

    ensure_store(store_root)
    resolution = resolve(project_dir, root=store_root)
    assert resolution.project_id is not None
    create_concept(
        title="Uses sqlite-vec",
        body="Mimer indexes with sqlite-vec.",
        concept_type="Reference",
        origin=resolution.project_id,
        scope="global",
        root=store_root,
    )
    _write_bad_concept(store_root)

    result = run_hook(
        "SessionStart",
        session_start_payload(cwd=str(project_dir)),
        store_root=store_root,
        cwd=project_dir,
    )

    assert result.returncode == 0
    context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "Uses sqlite-vec" in context

    # The bad file is logged once for the whole injection, not once per read.
    log_lines = [
        line
        for line in (store_root / LOG_FILENAME).read_text(encoding="utf-8").splitlines()
        if "broken.md" in line
    ]
    assert len(log_lines) == 1


@pytest.mark.parametrize(
    "malicious",
    ["../evil", "../../etc/passwd", "a/b", "..", ".", "foo.md", "with space", "UPPER"],
)
def test_concept_path_rejects_traversal_slug(malicious: str, store_root: Path) -> None:
    """The path-building chokepoint refuses any slug that is not a bare identifier,
    so a traversal-shaped slug never resolves outside the bundle (#25)."""

    with pytest.raises(ValueError):
        concept_path(malicious, store_root)


def test_retract_rejects_traversal_slug_without_deleting_the_target(store_root: Path) -> None:
    """Retract validates the slug before it reads or unlinks anything, so a
    concept-shaped file one level above the bundle survives a traversal slug (#25)."""

    ensure_store(store_root)
    concept = create_concept(
        title="Real concept",
        body="A genuine, concept-shaped file.",
        concept_type="Note",
        origin="proj-a",
        root=store_root,
    )

    # Plant a concept-shaped decoy one level above the bundle — the file a
    # ``../victim`` slug would resolve to and, unguarded, delete.
    decoy = bundle_dir(store_root).parent / "victim.md"
    decoy.write_text(concept_path(concept.slug, store_root).read_text(encoding="utf-8"))

    with pytest.raises(ValueError):
        retract_concept("../victim", root=store_root)

    assert decoy.exists()
