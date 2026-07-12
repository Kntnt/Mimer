"""Recall as an agent-invoked tool (Stage 4b; ADRs 0001, 0005, 0013).

Recall is project-scoped by default: it searches the current project's long-term
memory and returns cited results, or says honestly that nothing was found.
Widening is an explicit act that reaches other projects' long-term memory — but
never a project that has excluded itself from widened recall. This is the tool
the memory skill invokes, and the ``mimer-recall`` command it runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mimer.framing import frame
from mimer.index import Citation, search
from mimer.paths import store_root
from mimer.project import confirm_hint, resolve
from mimer.registry import PROJECTS_DIRNAME, Registry


@dataclass(frozen=True)
class RecallResult:
    """The outcome of a recall: cited hits, the scope used, and a user message."""

    citations: list[Citation]
    scope: str
    message: str

    def is_empty(self) -> bool:
        """Whether recall found nothing."""

        return not self.citations

    def rendered(self) -> str:
        """The full terminal output for the ``mimer-recall`` command.

        Mimer's own message is its trusted voice and stays outside the frame;
        the cited excerpts are recalled from untrusted memory, so they are
        wrapped in the data frame (ADR 0014). The advisory distiller filter is
        not the gate — a directive that slips past it into a Concept surfaces
        here as inert, fenced data rather than a bare command a future session
        might obey.
        """

        if self.is_empty():
            return self.message

        excerpts = "\n".join(
            f"[{c.source} · {c.date} · {c.heading}] {c.excerpt}" for c in self.citations
        )
        return f"{self.message}\n{frame(excerpts)}"


def recall(
    query: str,
    *,
    root: Path | None = None,
    project_id: str | None = None,
    cwd: Path | None = None,
    widen: bool = False,
    limit: int = 10,
) -> RecallResult:
    """Recall by meaning, scoped to the current project unless widened."""

    root = root or store_root()

    # Resolve the current project from ``project_id`` or the working directory; an
    # identity that needs confirmation recalls nothing but names the command and
    # candidate id that would resolve it (#34).
    if project_id is None:
        resolution = resolve(cwd or Path.cwd(), root=root)
        if resolution.project_id is None:
            hint = confirm_hint(resolution.candidate_id)
            message = f"Mimer: the project identity needs confirmation. {hint}"
            return RecallResult([], "unresolved", message)
        project_id = resolution.project_id

    if widen:
        citations = search(
            query,
            root=root,
            project_id=project_id,
            projects=_widenable_projects(root, current=project_id),
            limit=limit,
        )
        scope = "widened across projects"
    else:
        citations = search(query, root=root, project_id=project_id, limit=limit)
        scope = f'project "{project_id}"'

    if not citations:
        return RecallResult([], scope, f"Mimer: nothing relevant found in {scope}.")
    return RecallResult(citations, scope, f"Mimer: {len(citations)} result(s) from {scope}.")


def _widenable_projects(root: Path, *, current: str) -> list[str]:
    """The projects a widened recall may search: the current one, plus every
    other project that has not excluded itself from widening (ADR 0013)."""

    registry = Registry.load(root)

    # Consider both registered projects and any on disk, so a not-yet-registered
    # project's memory is reachable.
    known = set(registry.project_ids())
    projects_root = root / PROJECTS_DIRNAME
    if projects_root.exists():
        known |= {directory.name for directory in projects_root.iterdir() if directory.is_dir()}

    participating = {current}
    for project_id in known:
        if project_id != current and registry.is_widenable(project_id):
            participating.add(project_id)
    return sorted(participating)


def main(argv: list[str] | None = None) -> int:
    """``mimer-recall`` entry point: a scoped, optionally widened terminal search."""

    import argparse

    parser = argparse.ArgumentParser(
        prog="mimer-recall", description="Recall by meaning from Mimer's long-term memory."
    )
    parser.add_argument("query", nargs="+", help="the question to recall about")
    parser.add_argument(
        "--widen", action="store_true", help="widen recall across other projects' memory"
    )
    args = parser.parse_args(argv)

    result = recall(" ".join(args.query), root=store_root(), widen=args.widen)
    print(result.rendered())
    return 0
