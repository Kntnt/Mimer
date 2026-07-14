"""SessionEnd hook entry point (Stage 3b).

Fires at session close. It spools the payload and spawns the session-boundary
pass as a session-detached process, then returns immediately — so the batched
Haiku pass never delays session close (ADR 0023), the way the Stop hook already
spawns capture. The re-entrancy guard is enforced by the shared runner before
this handler is reached, so a Mimer-spawned session never runs a boundary pass
over itself. All gating (pause, project identity, per-project capture switch) and
the work itself live in the detached :mod:`mimer.boundary` process.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from typing import Any

from mimer.hooks.runner import run_hook
from mimer.hooks.stop import SPOOL_DIRNAME
from mimer.paths import store_root
from mimer.store import ensure_dir


def handle(payload: Mapping[str, Any]) -> None:
    """Spool the payload and launch the boundary pass detached, without blocking."""

    root = store_root()

    # Spool the payload to a private file the detached boundary process consumes
    # and then deletes.
    spool_dir = root / SPOOL_DIRNAME
    ensure_dir(spool_dir)
    handle_fd, spool_path = tempfile.mkstemp(dir=spool_dir, suffix=".json")
    with open(handle_fd, "w", encoding="utf-8") as spool_file:
        json.dump(dict(payload), spool_file)

    # Launch the boundary pass in its own session so it outlives this hook and runs
    # independently of the interactive session.
    subprocess.Popen(
        [sys.executable, "-m", "mimer.boundary", spool_path],
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def main() -> int:
    """Console entry point for the SessionEnd hook."""

    return run_hook("SessionEnd", handle)


if __name__ == "__main__":
    raise SystemExit(main())
