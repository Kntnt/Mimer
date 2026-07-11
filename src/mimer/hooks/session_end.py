"""SessionEnd hook entry point.

At this stage a no-op; the batched session digest arrives in ticket #7.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mimer.hooks.runner import run_hook


def handle(payload: Mapping[str, Any]) -> None:
    """Handle a SessionEnd event. No behaviour at this stage."""


def main() -> int:
    """Console entry point for the SessionEnd hook."""

    return run_hook("SessionEnd", handle)


if __name__ == "__main__":
    raise SystemExit(main())
