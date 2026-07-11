"""SessionStart hook entry point.

At this stage a no-op that bootstraps the store and exits cleanly; snapshot
injection arrives in ticket #4.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mimer.hooks.runner import run_hook


def handle(payload: Mapping[str, Any]) -> None:
    """Handle a SessionStart event. No behaviour at this stage."""


def main() -> int:
    """Console entry point for the SessionStart hook."""

    return run_hook("SessionStart", handle)


if __name__ == "__main__":
    raise SystemExit(main())
