"""SessionEnd hook entry point (Stage 3b).

Runs the session's one batched Haiku digest: a digest into the daily log, a
refresh of short-term memory's auto-maintained sections, and the archived
transcript. The shared runner enforces the re-entrancy guard first, so a
Mimer-spawned session never digests itself; when headless Claude is unavailable
the digest defers gracefully (ADR 0009).
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from mimer.digest import digest_session
from mimer.distill import distill_session
from mimer.gitreader import fold_git_log
from mimer.hooks.runner import run_hook
from mimer.paths import store_root
from mimer.project import resolve


def handle(payload: Mapping[str, Any]) -> None:
    """Run the digest, fold in git, then distil durable memory opportunistically."""

    digest_session(payload)

    # Opportunistic session-boundary work: fold git commits into the record and
    # distil durable entries. Both are deterministic, so they run even when the
    # digest deferred (ADRs 0003, 0004).
    root = store_root()
    cwd = Path(payload.get("cwd") or ".")
    resolution = resolve(cwd, root=root)
    if resolution.project_id is not None:
        fold_git_log(resolution.project_id, cwd, root)
        distill_session(resolution.project_id, root)


def main() -> int:
    """Console entry point for the SessionEnd hook."""

    return run_hook("SessionEnd", handle)


if __name__ == "__main__":
    raise SystemExit(main())
