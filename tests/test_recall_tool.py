"""Tests for recall as an agent tool (Stage 4b): scoped to the current project
by default, widened only as an explicit act that excluded projects never join,
always cited, and honestly empty (ADRs 0001, 0005, 0013).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from mimer.bundle import create_concept
from mimer.index import reindex
from mimer.longterm import daily_log_path
from mimer.project import resolve
from mimer.recall import recall
from mimer.registry import Registry
from mimer.store import ensure_store
from tests.harness import run_hook, session_start_payload

# Every test here loads the embedding model (directly or via a hook subprocess),
# so the session fixture prefetches it once before the suite runs (conftest.py).
pytestmark = pytest.mark.embedding

SKILL = Path(__file__).resolve().parent.parent / "skills" / "memory" / "SKILL.md"


def _seed(store_root: Path, pid: str, fact: str) -> None:
    path = daily_log_path(pid, "2026-06-01", store_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"## Note\n\n{fact}\n", encoding="utf-8")


def _register(store_root: Path, *pids: str) -> Registry:
    ensure_store(store_root)
    reg = Registry.load(store_root)
    for pid in pids:
        reg.create(pid, paths=[f"/work/{pid}"])
    reg.save()
    return reg


def test_recall_is_scoped_to_current_project_by_default(store_root: Path) -> None:
    """Default recall returns cited results from the current project only."""

    _register(store_root, "alpha", "bravo")
    _seed(store_root, "alpha", "deployment uses blue-green in project alpha")
    _seed(store_root, "bravo", "deployment secret handling for project bravo")
    reindex(store_root)

    result = recall("deployment", root=store_root, project_id="alpha")

    assert result.citations
    assert all(c.project_id == "alpha" for c in result.citations)
    assert not any("bravo" in c.text for c in result.citations)


def test_widening_is_explicit_and_excluded_project_never_surfaces(store_root: Path) -> None:
    """Widening reaches other projects, but never one excluded from widening."""

    reg = _register(store_root, "alpha", "bravo", "charlie")
    _seed(store_root, "alpha", "deployment uses blue-green in project alpha")
    _seed(store_root, "bravo", "deployment notes for project bravo")
    _seed(store_root, "charlie", "deployment schedule for project charlie is weekly")
    reindex(store_root)
    reg.set_widening("bravo", participate=False)
    reg.save()

    widened = recall("deployment", root=store_root, project_id="alpha", widen=True)

    projects = {c.project_id for c in widened.citations}
    assert "alpha" in projects
    assert "charlie" in projects
    assert "bravo" not in projects


def test_widened_recall_never_leaks_project_scoped_concept(store_root: Path) -> None:
    """A widened recall from the home project (client-b) gates Concepts by scope
    yet still reaches other projects' logs — the whole ADR 0013 fix for the
    confirmed leak in issue #20.

    In one pass the fix must: hide a foreign project-scoped Concept, still reach
    that same foreign project's log on the same topic (Concept and log go through
    different gates), let a global Concept cross, and surface the home project's
    own scoped Concept (visible only because recall threads the home identity into
    search — never because widening reached its origin)."""

    _register(store_root, "client-a", "client-b")

    # Foreign project client-a: a confidential, project-scoped Concept a widened
    # recall from client-b must never surface.
    create_concept(
        title="Client A secret rule",
        body="Client A's private API base path is internal-only and confidential.",
        concept_type="Decision",
        origin="client-a",
        scope="project",
        root=store_root,
    )

    # Foreign project client-a: a client-neutral, global Concept allowed to
    # travel across projects.
    create_concept(
        title="Global technique",
        body="Prefer dependency injection to keep seams testable across projects.",
        concept_type="Technique",
        origin="client-a",
        scope="global",
        root=store_root,
    )

    # Home project client-b: its own project-scoped Concept, visible under
    # widening only because client-b is the home identity threaded into search.
    create_concept(
        title="Client B home rule",
        body="Client B keeps its staging rollout details in the home playbook.",
        concept_type="Decision",
        origin="client-b",
        scope="project",
        root=store_root,
    )

    # Foreign project client-a: a log on the blocked Concept's topic, which
    # widening must still reach even while the Concept beside it stays hidden.
    _seed(store_root, "client-a", "Client A rolled out the private API base path last sprint.")
    reindex(store_root)

    foreign = recall(
        "client A private API base path internal-only",
        root=store_root,
        project_id="client-b",
        widen=True,
    )
    home_own = recall(
        "client B staging rollout home playbook",
        root=store_root,
        project_id="client-b",
        widen=True,
    )
    globaled = recall(
        "dependency injection testable seams",
        root=store_root,
        project_id="client-b",
        widen=True,
    )

    # The foreign scoped Concept never leaks, yet the foreign project's log on the
    # same topic does surface: the Concept and log gates diverge under widening.
    assert all("internal-only" not in citation.text for citation in foreign.citations)
    assert any(
        "last sprint" in citation.text and citation.project_id == "client-a"
        for citation in foreign.citations
    )

    # The home project's own scoped Concept surfaces under widening — recall must
    # thread its identity into search for the home gate to admit it.
    assert any("home playbook" in citation.text for citation in home_own.citations)

    # A global Concept still crosses projects.
    assert any("dependency injection" in citation.text for citation in globaled.citations)


def test_unanswerable_recall_states_nothing_found(store_root: Path) -> None:
    """An unanswerable recall is explicitly empty with a 'nothing found' message."""

    _register(store_root, "alpha")
    _seed(store_root, "alpha", "the deployment uses blue-green swaps")
    reindex(store_root)

    result = recall("marine biology of the deep ocean", root=store_root, project_id="alpha")

    assert result.is_empty()
    assert "nothing" in result.message.lower()


def test_recall_cli_is_scoped_and_honestly_empty(store_root: Path, project_dir: Path) -> None:
    """The mimer-recall command (the agent tool) scopes to the cwd's project and
    reports honestly when nothing is found."""

    executable = Path(sys.executable).parent / "mimer-recall"
    env = {**os.environ, "MIMER_HOME": str(store_root)}
    env.pop("MIMER_GUARD", None)
    reindex(store_root)

    result = subprocess.run(
        [str(executable), "quantum", "chromodynamics"],
        cwd=str(project_dir),
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "nothing" in result.stdout.lower()


def test_snapshot_manifest_lists_long_term_coverage(store_root: Path, project_dir: Path) -> None:
    """The injected snapshot's manifest lists the project's long-term coverage
    dates, so the agent can judge when recall is worth invoking."""

    resolution = resolve(project_dir, root=store_root)
    assert resolution.project_id is not None
    for day in ("2026-06-01", "2026-06-15", "2026-07-02"):
        path = daily_log_path(resolution.project_id, day, store_root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"## Note\n\nwork on {day}\n", encoding="utf-8")

    result = run_hook(
        "SessionStart",
        session_start_payload(cwd=str(project_dir)),
        store_root=store_root,
        cwd=project_dir,
    )

    context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "2026-06-01" in context
    assert "2026-07-02" in context
    assert "covers" in context.lower()


def test_skill_documents_recall_heuristics() -> None:
    """The skill carries recall-first heuristics and the widening act (the
    automated proxy for the manual 'agent invokes recall' residue)."""

    text = SKILL.read_text(encoding="utf-8").lower()
    assert "recall" in text
    assert "mimer-recall" in text
    assert "widen" in text
