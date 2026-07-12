"""Session-level pause: the throwaway-session control (ADR 0013).

Say "pause capture" before a sensitive session and nothing is recorded — no
extractive capture, no digest, no git fold, no distillation — until the session
ends or the user resumes. It is realised as a single marker file in the store:
the capture and digest paths check it before doing any work, and the SessionEnd
hook lifts it once the paused session ends, so the pause is naturally
session-scoped without threading a session id through every surface.

Pausing errs toward *not* recording: a marker left behind by a crashed session
suppresses capture until the next clean session end rather than leaking a
sensitive session's contents.
"""

from __future__ import annotations

from pathlib import Path

from mimer.paths import store_root
from mimer.store import FILE_MODE, ensure_store

# The marker file whose presence means "capture is paused".
PAUSE_FILENAME = "paused"


def pause_marker(root: Path) -> Path:
    """Path to the pause marker within ``root``."""

    return root / PAUSE_FILENAME


def is_paused(root: Path | None = None) -> bool:
    """Whether capture is currently paused."""

    return pause_marker(root or store_root()).exists()


def set_paused(root: Path | None = None) -> None:
    """Pause capture by creating the marker with owner-only permissions."""

    root = ensure_store(root)

    marker = pause_marker(root)
    marker.touch()
    marker.chmod(FILE_MODE)


def clear_paused(root: Path | None = None) -> None:
    """Resume capture by removing the marker; a no-op when not paused."""

    pause_marker(root or store_root()).unlink(missing_ok=True)
