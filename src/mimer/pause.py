"""The capture pause: the throwaway-session control (ADR 0013).

Say "pause capture" before a sensitive session and nothing is recorded — no
extractive capture, no boundary pass, no distillation — until the user resumes.
It is realised as a single marker file at the store root, so it is *store-wide*,
not session-scoped: the ``mimer-manage`` command that sets it runs as a plain
subprocess with no session id to key on, and the capture and boundary-pass paths
(each in their own detached process) check only the marker's presence.

The pause is therefore deliberately sticky. It is not lifted by a session
ending — an unrelated concurrent session must never lift a pause it did not ask
for, nor have its own capture silently suppressed and then resumed by another
session's boundary. Only an explicit "resume" clears it. To keep a forgotten or
crash-stranded pause from silently swallowing later sessions, its presence is
surfaced on every SessionStart and in ``mimer-manage health`` (never silent),
and it errs toward *not* recording while in effect.
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
