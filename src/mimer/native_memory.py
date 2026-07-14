"""Read and write Claude Code's native auto-memory switch, per project (ADR 0025).

Claude Code ships its own auto memory, on by default. Mimer replaces it rather
than racing it, because running both leaves a forgetting hole: the native
feature keeps its own copy of what it captures, so a fact forgotten or redacted
in Mimer can be silently re-injected by the native one (requirement 4). The
native feature is controlled per project by ``autoMemoryEnabled`` in the
project's ``.claude/settings.json``; absent means on, since it is on by default.

This module is the clean read/write seam over that one switch, shared by the
SessionStart warning and the ``disable-native-memory`` command that build on it
(vision Stages 5c and 8). Reads never mutate; a write sets ``autoMemoryEnabled``
to ``false`` and touches nothing else in the file, creating it (and ``.claude/``)
when absent. Mimer never flips the switch unbidden — writing a user's config
without consent is invasive (ADR 0025) — so ``disable_native_memory`` runs only
on the user's explicit request.
"""

from __future__ import annotations

from pathlib import Path

# The key Claude Code reads from a project's .claude/settings.json to decide
# whether its native auto memory is active. Absent is on, since it defaults on.
SETTINGS_KEY = "autoMemoryEnabled"


def settings_path(project_dir: Path) -> Path:
    """Path to a project's Claude Code settings file, ``.claude/settings.json``."""

    raise NotImplementedError


def is_native_memory_enabled(project_dir: Path) -> bool:
    """Whether Claude Code's native auto memory is on for ``project_dir``.

    Reads ``.claude/settings.json`` without mutating it. Absent file, absent key,
    or unreadable content all report enabled — the default-on state — so the
    caller warns rather than misses a native memory that may be live.
    """

    raise NotImplementedError


def disable_native_memory(project_dir: Path) -> None:
    """Set ``autoMemoryEnabled: false`` for ``project_dir``, preserving all else.

    Every other key already in ``.claude/settings.json`` is kept, in place; the
    file and its ``.claude/`` directory are created when absent. Only ever called
    on the user's explicit request (ADR 0025).
    """

    raise NotImplementedError
