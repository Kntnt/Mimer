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
from mimer.storeio import write_atomic

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

# A trailing marker flagging an entry as durable, so the cap keeps it (ADR 0017).
_DURABLE_MARKER = "[durable]"


@dataclass(frozen=True)
class Entry:
    """One date-stamped short-term memory entry.

    ``durable`` marks knowledge worth promoting to permanent memory; the cap ages
    out transient entries first and keeps durable ones until distillation
    promotes them (ADR 0017).
    """

    date: str
    text: str
    durable: bool = False


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
                sections[current].append(_entry_from_text(match.group(1), match.group(2).strip()))

    return sections


def _entry_from_text(date_stamp: str, text: str) -> Entry:
    """Build an entry, splitting off the trailing durable marker if present."""

    durable = text.endswith(_DURABLE_MARKER)
    if durable:
        text = text[: -len(_DURABLE_MARKER)].strip()
    return Entry(date_stamp, text, durable)


def render_short_term(project_id: str, sections: dict[str, list[Entry]]) -> str:
    """Render sections back to the canonical short-term memory Markdown."""

    parts = [f"# Short-term memory — {project_id}", ""]
    for name in SECTIONS:
        parts.append(f"## {name}")
        parts.append("")
        parts.extend(_render_entry(entry) for entry in sections[name])
        if sections[name]:
            parts.append("")

    return "\n".join(parts).rstrip("\n") + "\n"


def _render_entry(entry: Entry) -> str:
    """Render one entry, appending the durable marker when set."""

    suffix = f" {_DURABLE_MARKER}" if entry.durable else ""
    return f"- [{entry.date}] {entry.text}{suffix}"


def merge_documents(target_content: str, source_content: str, target_id: str) -> str:
    """Merge two short-term memory documents into one, losing no entry.

    Used when a project merge (ADR 0008) folds a source project whose short-term
    file collides with the target's. Entries are unioned per section in
    target-then-source order; an entry present in both — same date, text and
    durability — is kept once. Non-entry lines are dropped, as everywhere the
    machine manages this file, and the result is rendered under ``target_id``.
    """

    target_sections = parse_short_term(target_content)
    source_sections = parse_short_term(source_content)

    # Union each section, preserving the target's entries first and appending the
    # source's newcomers, so a shared entry is never duplicated.
    merged: dict[str, list[Entry]] = {}
    for name in SECTIONS:
        entries = list(target_sections[name])
        seen = set(entries)
        for entry in source_sections[name]:
            if entry not in seen:
                entries.append(entry)
                seen.add(entry)
        merged[name] = entries

    return render_short_term(target_id, merged)


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
        write_atomic(path, empty_short_term(project_id))

    return path


def read_short_term(project_id: str, root: Path | None = None) -> str:
    """Return a project's short-term memory, or the empty template if unseen."""

    path = short_term_path(project_id, root)
    if path.exists():
        return path.read_text(encoding="utf-8")
    return empty_short_term(project_id)
