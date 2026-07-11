"""The short-term memory file: the capped, project-scoped working set injected
each session. Plain Markdown with a fixed set of sections (their names and order
are settled here, Stage 1).

Two classes of section:

- **Auto-refreshed** (``Active threads``, ``Pending decisions``) — rewritten by
  the session digest (#7) so the snapshot stays current for users who never say
  "remember".
- **Curated** (``Notes``) — written by the memory skill on request (#5).

Every entry is a date-stamped bullet: ``- [YYYY-MM-DD] text``.
"""

from __future__ import annotations

from pathlib import Path

from mimer.paths import store_root
from mimer.registry import project_dir
from mimer.store import FILE_MODE

SHORT_TERM_FILENAME = "short-term.md"

# Section headings, in the order they appear in the file.
AUTO_REFRESHED_SECTIONS = ("Active threads", "Pending decisions")
CURATED_SECTIONS = ("Notes",)
SECTIONS = (*AUTO_REFRESHED_SECTIONS, *CURATED_SECTIONS)


def short_term_path(project_id: str, root: Path | None = None) -> Path:
    """Path to a project's short-term memory file."""

    return project_dir(project_id, root or store_root()) / SHORT_TERM_FILENAME


def empty_short_term(project_id: str) -> str:
    """The well-formed, empty short-term memory template for a new project."""

    sections = "\n\n".join(f"## {name}" for name in SECTIONS)
    return f"# Short-term memory — {project_id}\n\n{sections}\n"


def ensure_short_term(project_id: str, root: Path | None = None) -> Path:
    """Create the short-term memory file with the empty template if it is absent.

    Returns the file path. Existing content is never overwritten.
    """

    path = short_term_path(project_id, root)

    if not path.exists():
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.write_text(empty_short_term(project_id), encoding="utf-8")
        path.chmod(FILE_MODE)

    return path


def read_short_term(project_id: str, root: Path | None = None) -> str:
    """Return a project's short-term memory, or the empty template if unseen."""

    path = short_term_path(project_id, root)
    if path.exists():
        return path.read_text(encoding="utf-8")
    return empty_short_term(project_id)
