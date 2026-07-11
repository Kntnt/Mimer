"""SessionEnd hook entry point (Stage 3b).

Runs the session's one batched Haiku digest: a digest into the daily log, a
refresh of short-term memory's auto-maintained sections, and the archived
transcript. The shared runner enforces the re-entrancy guard first, so a
Mimer-spawned session never digests itself; when headless Claude is unavailable
the digest defers gracefully (ADR 0009).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mimer.digest import digest_session
from mimer.hooks.runner import run_hook


def handle(payload: Mapping[str, Any]) -> None:
    """Run the batched session digest for this session."""

    digest_session(payload)


def main() -> int:
    """Console entry point for the SessionEnd hook."""

    return run_hook("SessionEnd", handle)


if __name__ == "__main__":
    raise SystemExit(main())
