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

import json
from pathlib import Path
from typing import Any

# The key Claude Code reads from a project's .claude/settings.json to decide
# whether its native auto memory is active. Absent is on, since it defaults on.
SETTINGS_KEY = "autoMemoryEnabled"


def settings_path(project_dir: Path) -> Path:
    """Path to a project's Claude Code settings file, ``.claude/settings.json``."""

    return project_dir / ".claude" / "settings.json"


def is_native_memory_enabled(project_dir: Path) -> bool:
    """Whether Claude Code's native auto memory is on for ``project_dir``.

    Reads ``.claude/settings.json`` without mutating it. Absent file, absent key,
    or unreadable content all report enabled — the default-on state — so the
    caller warns rather than misses a native memory that may be live. Only an
    explicit ``false`` reports off.
    """

    # A file we cannot parse tells us nothing about the switch, so we cannot
    # confirm it is off — report on and let the caller warn.
    try:
        settings = _load_settings(settings_path(project_dir))
    except (json.JSONDecodeError, ValueError):
        return True

    return settings.get(SETTINGS_KEY, True) is not False


def disable_native_memory(project_dir: Path) -> None:
    """Set ``autoMemoryEnabled: false`` for ``project_dir``, preserving all else.

    Every other key already in ``.claude/settings.json`` is kept, in place; the
    file and its ``.claude/`` directory are created when absent. Only ever called
    on the user's explicit request (ADR 0025).

    Raises:
        json.JSONDecodeError: when the existing file holds non-empty, unparseable
            content, or ValueError when its top level is not a JSON object —
            either way the file is left untouched rather than blindly overwritten,
            so real user config is never destroyed.
    """

    # Read the existing settings first, so a non-empty but unparseable file
    # raises before any write and the user's config is never clobbered.
    path = settings_path(project_dir)
    settings = _load_settings(path)
    settings[SETTINGS_KEY] = False

    # Serialise the whole object — updating the key in place preserves the order
    # and every other setting — and create .claude/ on the way if it is absent.
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")


def _load_settings(path: Path) -> dict[str, Any]:
    """Parse ``path`` into a settings object; absent or empty is an empty object.

    An empty or whitespace-only file has nothing to preserve, so it reads as
    ``{}`` rather than an error — a bare ``touch``-created settings file is a
    normal starting state. Genuinely malformed non-empty content raises, so a
    write path can refuse to clobber it.

    Raises:
        json.JSONDecodeError: when non-empty content is not valid JSON.
        ValueError: when the top-level JSON value is not an object.
    """

    if not path.exists():
        return {}

    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return {}

    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError(f"{path} does not contain a JSON object")
    return parsed
