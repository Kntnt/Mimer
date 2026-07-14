"""Git as a citation source, not a capture source (issue #66, ADR 0021).

Git is purely additive here: a memory entry distilled from work in a git project
carries the current HEAD commit's ``git:<sha>`` as an extra provenance anchor,
quoting the commit subject so the citation stays checkable even after a history
rewrite changes the sha. The lookup is reactive and lightweight — a single
``git log -1`` at HEAD, never a walk of history — and behind the redaction pass.

Verifiability must not depend on git: a non-git project, or any git error, yields
no citation and never a crash, and its distilled facts still recall with a
git-free cited excerpt. The bulk commit-message fold is gone (ADR 0021); this
covers only the replacement.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest

from mimer.boundary import run_boundary_pass
from mimer.bundle import Concept, list_concepts
from mimer.index import reindex
from mimer.longterm import append_entry
from mimer.recall import recall
from mimer.store import ensure_store
from mimer.vcs import head_commit
from tests.gitutil import commit, commit_shas, commit_subjects, init_repo, rewrite_history
from tests.transcript_fixture import write_transcript

# The recall and reindex assertions load the embedding model, so the whole module
# is marked for the session-scoped prefetch (conftest.py), like test_boundary.py.
pytestmark = pytest.mark.embedding

TODAY = date(2026, 7, 11)

# A well-formed boundary reply whose one durable fact is promoted into a Concept —
# the entry that, in a git project, must carry the commit citation.
REPLY = """## Active threads
- none

## Pending decisions
- none

## Durable facts
- The project stores its vectors in sqlite-vec
"""

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _payload(cwd: Path, transcript: Path, *, session_id: str = "sess-git") -> dict[str, object]:
    return {
        "session_id": session_id,
        "hook_event_name": "SessionEnd",
        "reason": "other",
        "cwd": str(cwd),
        "transcript_path": str(transcript),
    }


def _seed_raw_record(pid: str, root: Path, day: date, text: str) -> None:
    """Append a captured-turn-shaped entry to the day's raw long-term record."""

    entry = f"### 10:00 — turn abcd1234\n- User: what did we decide?\n- Assistant: {text}\n"
    append_entry(pid, day.isoformat(), entry, root)


def _run_boundary(repo: Path, root: Path, pid: str, *, reply: str = REPLY) -> None:
    """Seed a raw record and run one completed boundary pass over ``repo``."""

    _seed_raw_record(pid, root, TODAY, "we chose sqlite-vec for the vector store")
    transcript = write_transcript(repo / "t.jsonl", [("q", "a", "2026-07-11T15:00:00Z")])
    run_boundary_pass(_payload(repo, transcript), root=root, haiku=lambda _: reply, today=TODAY)


def _distilled_concept(root: Path) -> Concept:
    """The single sqlite-vec Concept the boundary pass promoted from REPLY."""

    return next(c for c in list_concepts(root) if "sqlite-vec" in c.body)


def _git_citations(concept: Concept) -> list[tuple[str, str]]:
    """The (source, excerpt) of every ``git:`` citation on a Concept."""

    return [(s.source, s.excerpt) for s in concept.citations if s.source.startswith("git:")]


# --- head_commit: the reactive HEAD lookup ---------------------------------


def test_head_commit_returns_sha_subject_and_date(tmp_path: Path) -> None:
    """head_commit reads HEAD reactively: the full sha, the commit subject (the
    checkable excerpt) and an ISO commit date."""

    repo = init_repo(tmp_path / "repo", commit=True)
    sha = commit(repo, "Wire up the sqlite-vec vector index")

    result = head_commit(repo)

    assert result is not None
    assert result.sha == sha
    assert result.subject == "Wire up the sqlite-vec vector index"
    assert _ISO_DATE.match(result.date), f"commit date is not ISO: {result.date!r}"


def test_head_commit_is_none_outside_a_git_repository(project_dir: Path) -> None:
    """A non-git directory yields no commit — the anchor is git-free by design."""

    assert head_commit(project_dir) is None


def test_head_commit_is_none_when_git_errors(tmp_path: Path) -> None:
    """A repository with no HEAD (freshly init'd, no commit) makes ``git log`` exit
    non-zero; the error is absorbed into None, never raised — no citation, no crash."""

    repo = tmp_path / "empty"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)

    assert head_commit(repo) is None


# --- AC1: an entry that corresponds to a commit is recalled cited with git:<sha> ---


def test_distilled_fact_in_a_git_project_is_recalled_cited_with_its_git_sha(
    store_root: Path, resolve_project: Callable[[Path], str], tmp_path: Path
) -> None:
    """A fact distilled in a git project is recallable, and the Concept behind the
    recalled excerpt is cited with the HEAD commit's ``git:<sha>`` and its subject
    as the quoted excerpt (AC1, ADR 0021)."""

    ensure_store(store_root)
    repo = init_repo(tmp_path / "repo", commit=True)
    sha = commit(repo, "Add the sqlite-vec vector index")
    pid = resolve_project(repo)

    _run_boundary(repo, store_root, pid)

    # The distilled Concept carries the commit as an additive git citation.
    concept = _distilled_concept(store_root)
    assert (f"git:{sha}", "Add the sqlite-vec vector index") in _git_citations(concept)

    # And the fact is genuinely recalled: the Concept surfaces for a query about it.
    reindex(store_root)
    result = recall("sqlite-vec vector store", project_id=pid, root=store_root)
    assert not result.is_empty()
    assert any(c.source == f"permanent/{concept.slug}.md" for c in result.citations)


# --- AC2: after a history rewrite, the quoted excerpt still checks out ---


def test_git_citation_excerpt_survives_a_history_rewrite(
    store_root: Path, resolve_project: Callable[[Path], str], tmp_path: Path
) -> None:
    """After a history rewrite the stored ``git:<sha>`` is stale — the sha is gone
    from history — but the quoted excerpt still checks out: a commit with that
    subject still exists, so the excerpt, not the sha, is what survives (AC2)."""

    ensure_store(store_root)
    repo = init_repo(tmp_path / "repo", commit=True)
    original_sha = commit(repo, "Add the recall reranker")
    pid = resolve_project(repo)
    _run_boundary(repo, store_root, pid)

    ((source, excerpt),) = _git_citations(_distilled_concept(store_root))
    assert source == f"git:{original_sha}"

    # Rewrite history: the sha changes, the subject is preserved.
    rewritten_sha = rewrite_history(repo)
    assert rewritten_sha != original_sha

    # The cited sha is now stale — absent from the rewritten history — yet the
    # quoted excerpt still finds its commit, so the citation stays checkable.
    assert original_sha not in commit_shas(repo)
    assert excerpt in commit_subjects(repo)


# --- AC3 + AC4: a non-git project is unaffected and keeps full cited recall ---


def test_non_git_project_gets_no_git_citation_but_keeps_full_cited_recall(
    store_root: Path, resolve_project: Callable[[Path], str], project_dir: Path
) -> None:
    """A non-git project distils, recalls and cites exactly as before: no git
    citation is attached, the pass does not crash, and the fact still recalls with
    a git-free quoted excerpt — verifiability never depends on git (AC3, AC4)."""

    ensure_store(store_root)
    pid = resolve_project(project_dir)

    _seed_raw_record(pid, store_root, TODAY, "we chose sqlite-vec for the vector store")
    transcript = write_transcript(project_dir / "t.jsonl", [("q", "a", "2026-07-11T15:00:00Z")])
    result = run_boundary_pass(
        _payload(project_dir, transcript), root=store_root, haiku=lambda _: REPLY, today=TODAY
    )

    assert result.status == "completed"
    concept = _distilled_concept(store_root)
    assert _git_citations(concept) == []

    reindex(store_root)
    recalled = recall("sqlite-vec vector store", project_id=pid, root=store_root)
    assert not recalled.is_empty()
    assert recalled.citations[0].excerpt.strip()


def test_git_project_without_a_commit_yields_no_citation_and_no_crash(
    store_root: Path, resolve_project: Callable[[Path], str], tmp_path: Path
) -> None:
    """A git project whose HEAD does not resolve (no commit yet) makes the git
    lookup error; the boundary pass completes cleanly and attaches no citation, so
    a git error is handled without a crash and without a false anchor (AC3)."""

    ensure_store(store_root)
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    pid = resolve_project(repo)

    _run_boundary(repo, store_root, pid)

    result_concept = _distilled_concept(store_root)
    assert _git_citations(result_concept) == []
