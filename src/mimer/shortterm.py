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

import re
from dataclasses import dataclass
from pathlib import Path

from mimer.paths import store_root
from mimer.registry import project_dir
from mimer.store import FILE_MODE

SHORT_TERM_FILENAME = "short-term.md"

# Section headings, in the order they appear in the file.
AUTO_REFRESHED_SECTIONS = ("Active threads", "Pending decisions")
CURATED_SECTIONS = ("Notes",)
SECTIONS = (*AUTO_REFRESHED_SECTIONS, *CURATED_SECTIONS)

# Default cap on the total number of short-term entries. Until capture exists
# (#6/#8) the cap only warns; the value is tunable via configuration later.
SHORT_TERM_CAP = 30

# A date-stamped bullet entry: ``- [YYYY-MM-DD] text``.
_ENTRY_RE = re.compile(r"^-\s*\[(\d{4}-\d{2}-\d{2})\]\s*(.*)$")


@dataclass(frozen=True)
class Entry:
    """One date-stamped short-term memory entry."""

    date: str
    text: str


def parse_short_term(content: str) -> dict[str, list[Entry]]:
    """Parse short-term memory into each section's dated entries.

    Non-entry lines are ignored so the machine-managed structure survives a
    hand-edit. Every known section is present in the result, in order.
    """

    sections: dict[str, list[Entry]] = {name: [] for name in SECTIONS}

    # Walk the file, attributing each dated bullet to the section it sits under.
    current: str | None = None
    for line in content.splitlines():
        if line.startswith("## "):
            heading = line[3:].strip()
            current = heading if heading in sections else None
        elif current is not None:
            match = _ENTRY_RE.match(line.strip())
            if match:
                sections[current].append(Entry(match.group(1), match.group(2).strip()))

    return sections


def render_short_term(project_id: str, sections: dict[str, list[Entry]]) -> str:
    """Render sections back to the canonical short-term memory Markdown."""

    parts = [f"# Short-term memory — {project_id}", ""]
    for name in SECTIONS:
        parts.append(f"## {name}")
        parts.append("")
        parts.extend(f"- [{entry.date}] {entry.text}" for entry in sections[name])
        if sections[name]:
            parts.append("")

    return "\n".join(parts).rstrip("\n") + "\n"


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
