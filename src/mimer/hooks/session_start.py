"""SessionStart hook entry point (Stage 1).

Resolves the project for the session's working directory and injects the
snapshot — short-term memory only at this stage; the profile and manifest join
in later tickets. Injection happens on every SessionStart source, re-injecting
deliberately on ``compact`` so a compacted context never loses its memory
(ADR 0016), and it is announced, never silent (ADR 0014).
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

from mimer.bundle import concept_headlines, render_profile
from mimer.distill import drain_distilled
from mimer.hooks.runner import run_hook
from mimer.manifest import long_term_manifest
from mimer.paths import store_root
from mimer.project import resolve
from mimer.shortterm import ensure_short_term, read_short_term
from mimer.snapshot import DATA_FRAME_HEADER, build_snapshot


def handle(payload: Mapping[str, Any]) -> None:
    """Resolve the project and inject its snapshot as additional context."""

    root = store_root()
    cwd = Path(payload.get("cwd") or ".")
    source = str(payload.get("source") or "startup")

    # Resolve the project; an identity that needs confirmation injects nothing
    # but says so, rather than binding memory to an unconfirmed directory.
    resolution = resolve(cwd, root=root)
    if resolution.project_id is None:
        _emit(
            f"{DATA_FRAME_HEADER}\n\nMimer: this directory's project identity needs "
            "confirmation; no memory was injected."
        )
        return

    # Ensure the short-term file exists, then inject its framed, aged snapshot,
    # the pinned profile, and the manifest (long-term coverage + Concept headlines).
    ensure_short_term(resolution.project_id, root)
    short_term_text = read_short_term(resolution.project_id, root)
    snapshot = build_snapshot(
        resolution.project_id,
        short_term_text,
        today=date.today(),
        source=source,
        manifest=_manifest(resolution.project_id, root),
        profile=render_profile(root),
        distilled=drain_distilled(resolution.project_id, root),
    )
    _emit(snapshot)


def _manifest(project_id: str, root: Path) -> str:
    """The memory manifest: long-term coverage plus visible Concept headlines."""

    manifest = long_term_manifest(project_id, root)
    headlines = concept_headlines(root, project_id=project_id)
    if headlines:
        joined = "; ".join(headlines)
        manifest += f"\nPermanent memory: {len(headlines)} concept(s) — {joined}"
    return manifest


def _emit(additional_context: str) -> None:
    """Write the SessionStart context-injection payload to stdout."""

    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": additional_context,
        }
    }
    sys.stdout.write(json.dumps(output))


def main() -> int:
    """Console entry point for the SessionStart hook."""

    return run_hook("SessionStart", handle)


if __name__ == "__main__":
    raise SystemExit(main())
