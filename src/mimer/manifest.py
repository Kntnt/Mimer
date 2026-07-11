"""The memory manifest injected with the snapshot: a compact statement of what
memory holds, so the agent has grounds to judge when recall is worth invoking.

Stage 4b adds the long-term half — the coverage dates of a project's daily logs.
The Concept-headline half joins with permanent memory (Stage 5a).
"""

from __future__ import annotations

from pathlib import Path

from mimer.longterm import long_term_dir
from mimer.paths import store_root


def long_term_dates(project_id: str, root: Path | None = None) -> list[str]:
    """Return the sorted dates a project's long-term memory covers."""

    directory = long_term_dir(project_id, root or store_root())
    if not directory.exists():
        return []
    return sorted(log.stem for log in directory.glob("*.md"))


def long_term_manifest(project_id: str, root: Path | None = None) -> str:
    """A one-line manifest of a project's long-term coverage."""

    dates = long_term_dates(project_id, root)
    if not dates:
        return "Long-term memory: none recorded yet."
    if len(dates) == 1:
        return f"Long-term memory covers {dates[0]} (1 daily log)."
    return f"Long-term memory covers {dates[0]} to {dates[-1]} ({len(dates)} daily logs)."
