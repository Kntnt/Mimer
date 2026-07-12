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
from mimer.pause import clear_paused, is_paused
from mimer.project import resolve
from mimer.registry import Registry


def handle(payload: Mapping[str, Any]) -> None:
    """Run the digest, fold in git, then distil durable memory opportunistically."""

    # The digest owns its own pause and capture gating; it returns without work
    # for a paused or capture-disabled session.
    digest_session(payload)

    root = store_root()

    # A paused session records nothing at the boundary either, and the pause
    # lifts now that the session that asked for it has ended (#35).
    if is_paused(root):
        clear_paused(root)
        return

    cwd = Path(payload.get("cwd") or ".")
    resolution = resolve(cwd, root=root)
    if resolution.project_id is None:
        return

    # Opportunistic session-boundary work, deterministic so it runs even when the
    # digest deferred (ADRs 0003, 0004). Git folding is recording, so it honours
    # the per-project capture switch; distillation bridges already-curated memory
    # and still runs (ADR 0013).
    project_id = resolution.project_id
    if Registry.load(root).capture_enabled(project_id):
        fold_git_log(project_id, cwd, root)
    distill_session(project_id, root)


def main() -> int:
    """Console entry point for the SessionEnd hook."""

    return run_hook("SessionEnd", handle)


if __name__ == "__main__":
    raise SystemExit(main())
