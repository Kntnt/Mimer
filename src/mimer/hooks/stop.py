"""Stop hook entry point (Stage 3a).

Fires per assistant turn. It spools the payload and spawns capture as a
session-detached process, then returns immediately — so extractive capture never
delays the session (ADR 0009). The re-entrancy guard is enforced by the shared
runner before this handler is reached, so a Mimer-spawned session never captures
itself. Exchanges ended by a user interrupt are not captured — a documented
limitation.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from typing import Any

from mimer.hooks.runner import run_hook
from mimer.paths import store_root

SPOOL_DIRNAME = "spool"


def handle(payload: Mapping[str, Any]) -> None:
    """Spool the payload and launch capture detached, without blocking."""

    root = store_root()

    # Spool the payload to a private file the detached capture process consumes
    # and then deletes.
    spool_dir = root / SPOOL_DIRNAME
    spool_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    handle_fd, spool_path = tempfile.mkstemp(dir=spool_dir, suffix=".json")
    with open(handle_fd, "w", encoding="utf-8") as spool_file:
        json.dump(dict(payload), spool_file)

    # Launch capture in its own session so it outlives this hook and runs
    # independently of the interactive session.
    subprocess.Popen(
        [sys.executable, "-m", "mimer.capture", spool_path],
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def main() -> int:
    """Console entry point for the Stop hook."""

    return run_hook("Stop", handle)


if __name__ == "__main__":
    raise SystemExit(main())
