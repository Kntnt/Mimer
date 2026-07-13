"""The memory manifest injected with the snapshot: a compact statement of what
memory holds, so the agent has grounds to judge when recall is worth invoking.

Stage 4b adds the long-term half — the coverage dates of a project's daily logs.
The Concept-headline half joins with permanent memory (Stage 5a).
"""

from __future__ import annotations

from pathlib import Path

from mimer.storewalk import daily_log_days


def long_term_manifest(project_id: str, root: Path | None = None) -> str:
    """A one-line manifest of a project's long-term coverage."""

    dates = daily_log_days(project_id, root)
    if not dates:
        return "Long-term memory: none recorded yet."
    if len(dates) == 1:
        return f"Long-term memory covers {dates[0]} (1 daily log)."
    return f"Long-term memory covers {dates[0]} to {dates[-1]} ({len(dates)} daily logs)."
