"""Stop hook entry point.

At this stage a no-op; extractive capture of the exchange arrives in ticket #6.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mimer.hooks.runner import run_hook


def handle(payload: Mapping[str, Any]) -> None:
    """Handle a Stop event. No behaviour at this stage."""


def main() -> int:
    """Console entry point for the Stop hook."""

    return run_hook("Stop", handle)


if __name__ == "__main__":
    raise SystemExit(main())
