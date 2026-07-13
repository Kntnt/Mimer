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
from datetime import date
from pathlib import Path

from mimer.paths import store_root
from mimer.registry import project_dir
from mimer.storeio import project_lock, write_atomic
from mimer.storewalk import disk_project_ids

SHORT_TERM_FILENAME = "short-term.md"

# A store-level sentinel recording that every project's short-term file has been
# rewritten from the pre-#40 trailing durable-marker format into the current
# structural-slot format. Its presence gates the one-time migration below, which
# must never re-run over already-migrated content (see migrate_short_term_files).
SHORT_TERM_FORMAT_MARKER = ".short-term-format-v2"

# Section headings, in the order they appear in the file.
AUTO_REFRESHED_SECTIONS = ("Active threads", "Pending decisions")
CURATED_SECTIONS = ("Notes",)
SECTIONS = (*AUTO_REFRESHED_SECTIONS, *CURATED_SECTIONS)

# Default cap on the total number of short-term entries. Until capture exists
# (#6/#8) the cap only warns; the value is tunable via configuration later.
SHORT_TERM_CAP = 30

# A durable entry carries the marker in a fixed structural slot — immediately
# after the date bracket, with no separating space — so durability rides
# out-of-band rather than being sniffed from the free text. A transient entry
# always has a space after the date bracket, a position free text can never
# occupy, so content that merely contains or ends in ``[durable]`` is never
# misread as durable nor has those words stripped (ADR 0017, #40).
_DURABLE_MARKER = "[durable]"

# A date-stamped bullet entry, ``- [YYYY-MM-DD] text``, optionally carrying the
# durable marker flush against the date bracket: ``- [YYYY-MM-DD][durable] text``.
_ENTRY_RE = re.compile(r"^-\s*\[(\d{4}-\d{2}-\d{2})\](\[durable\])?\s*(.*)$")

# The pre-#40 on-disk format, where the durable marker was a trailing free-text
# suffix (``- [YYYY-MM-DD] text [durable]``). Read only by the one-time migration,
# which alone knows a legacy file's trailing ``[durable]`` was always a durable
# flag — a fact the current parser cannot recover, since a legacy durable line and
# a new-format transient whose text legitimately ends in ``[durable]`` collide.
_LEGACY_ENTRY_RE = re.compile(r"^-\s*\[(\d{4}-\d{2}-\d{2})\]\s*(.*)$")


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
                date_stamp, durable_marker, text = match.groups()
                entry = Entry(date_stamp, text.strip(), durable=bool(durable_marker))
                sections[current].append(entry)

    return sections


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
    """Render one entry, placing the durable marker in its out-of-band slot.

    The marker sits flush against the date bracket for a durable entry; a
    transient entry keeps the plain space there, so the two are told apart
    structurally rather than by inspecting the text (ADR 0017, #40).
    """

    marker = _DURABLE_MARKER if entry.durable else ""
    return f"- [{entry.date}]{marker} {entry.text}"


def _parse_legacy(content: str) -> dict[str, list[Entry]]:
    """Parse short-term content written in the pre-#40 trailing-marker format.

    In that format the durable flag rode as a trailing ``[durable]`` suffix on the
    free text, so a line ending in the marker was durable and the marker was
    stripped from the text. This is faithful to how the pre-#40 parser read the
    file: because it sniffed the same trailing substring, a transient entry whose
    text genuinely ended in ``[durable]`` could never have been persisted — it was
    always read (and re-rendered) as durable — so treating every trailing
    ``[durable]`` here as durable recovers exactly what that version stored.
    """

    sections: dict[str, list[Entry]] = {name: [] for name in SECTIONS}

    # Walk the file as parse_short_term does, but split the durable flag off the
    # trailing suffix rather than the structural slot.
    current: str | None = None
    for line in content.splitlines():
        if line.startswith("## "):
            heading = line[3:].strip()
            current = heading if heading in sections else None
        elif current is not None:
            match = _LEGACY_ENTRY_RE.match(line.strip())
            if match:
                date_stamp, text = match.group(1), match.group(2).strip()
                durable = text.endswith(_DURABLE_MARKER)
                if durable:
                    text = text[: -len(_DURABLE_MARKER)].strip()
                sections[current].append(Entry(date_stamp, text, durable))

    return sections


def migrate_short_term_content(project_id: str, content: str) -> str:
    """Rewrite one pre-#40 short-term document into the current structural format."""

    return render_short_term(project_id, _parse_legacy(content))


def _has_structural_durable_marker(content: str) -> bool:
    """Whether any entry carries the durable marker in its structural slot — the
    unambiguous tell that a file is already in the post-#40 format.

    Only the structural slot counts: the marker flush against the date bracket,
    which :data:`_ENTRY_RE` captures as its second group. The legacy format always
    wrote a space after that bracket, so a match here cannot be a legacy line, and
    free text merely containing ``][durable]`` — an array index, say — never
    matches. This is why the migration sweep tests it rather than a raw substring,
    which would wrongly flag such a legacy file as already migrated (#40).
    """

    return any(
        (match := _ENTRY_RE.match(line.strip())) is not None and match.group(2) is not None
        for line in content.splitlines()
    )


def migrate_short_term_files(root: Path | None = None) -> int:
    """One-time upgrade of every project's short-term file to the structural
    durable-marker format (#40); returns the number of files rewritten.

    The pre-#40 code wrote the durable marker as a trailing free-text suffix
    (``- [date] text [durable]``); the current format carries it in a structural
    slot flush against the date bracket (``- [date][durable] text``). Read with
    the current parser a legacy durable line yields ``durable=False`` and leaks the
    literal ``[durable]`` into its text — a silent loss the parser cannot later
    undo, since the next render persists the corruption in the new format. This
    sweep rewrites each legacy file once, before any new-format read misreads it.

    It is the counterpart of :func:`mimer.store.heal_permissions`: run at
    install/upgrade, gated by a store-level marker so the rewrite happens exactly
    once. The gate is load-bearing — a legacy durable line and a new-format
    transient whose text legitimately ends in ``[durable]`` are byte-identical, so
    re-running the trailing-marker rewrite over already-migrated content would
    corrupt the very entries the structural format protects. A no-op when the store
    does not yet exist or has already been migrated.

    Args:
        root: Store root to migrate; defaults to :func:`mimer.paths.store_root`.

    Returns:
        The number of project short-term files rewritten.
    """

    root = root or store_root()

    # Gate the rewrite on the store-level marker: legacy and new content are
    # byte-ambiguous, so this must run exactly once, on the first upgrade.
    marker = root / SHORT_TERM_FORMAT_MARKER
    if not root.exists() or marker.exists():
        return 0

    # Rewrite every project's legacy file — enumerated on disk via the store walk,
    # so an orphan not in the registry is migrated too — each under its own lock,
    # so a live writer (the memory skill or the digest) cannot lose an update
    # (ADR 0011).
    migrated = 0
    for project_id in disk_project_ids(root):
        # A project directory without a short-term file yet has nothing to migrate.
        path = short_term_path(project_id, root)
        if not path.exists():
            continue

        with project_lock(project_id, root=root):
            content = path.read_text(encoding="utf-8")

            # Skip a file already in the new format: the store marker is written
            # only after this loop, so a crash mid-sweep would otherwise let a retry
            # re-parse an already-rewritten durable line with the legacy parser and
            # corrupt it. The tell is the marker in its structural slot — flush
            # against the date bracket — which the legacy format, always writing a
            # space there, can never produce. A raw ``][durable]`` substring test
            # would also fire on free text such as ``arr[i][durable]``, wrongly
            # skipping a genuine legacy file and letting that very corruption
            # through (issue #40).
            if _has_structural_durable_marker(content):
                continue

            write_atomic(path, migrate_short_term_content(project_id, content))
            migrated += 1

    # Record that the structural format is established, so the ambiguous rewrite
    # never runs again over content the new writers have since produced.
    write_atomic(marker, "")
    return migrated


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


def evict_transient(sections: dict[str, list[Entry]], cap: int) -> list[Entry]:
    """Evict transient entries oldest-first until at ``cap``, or none remain.

    Returns the evicted entries in eviction order. Durable entries are never
    removed here — they leave short-term only by being promoted to a Concept
    (ADR 0017) — so a caller can tell "cleared the cap" from "only durables left
    over cap". This is the one cap-enforcement every writer to short-term shares
    (the curated write and the digest refresh), so neither can grow the file past
    the cap the other honours (#40).
    """

    def total() -> int:
        return sum(len(entries) for entries in sections.values())

    evicted: list[Entry] = []
    while total() > cap:
        oldest = min(
            (
                (name, index, entry)
                for name, entries in sections.items()
                for index, entry in enumerate(entries)
                if not entry.durable
            ),
            key=lambda candidate: candidate[2].date,
            default=None,
        )
        if oldest is None:
            break
        name, index, entry = oldest
        sections[name].pop(index)
        evicted.append(entry)
    return evicted


def aged_out_block(evicted: list[Entry], today: date) -> str:
    """Render an aged-out daily-log block holding the evicted entries verbatim.

    Ageing out is itself a write: the evicted entry is appended to today's daily
    log so the cap never drops a word, only relocates it (ADR 0017).
    """

    lines = [f"## Aged out of short-term ({today.isoformat()})"]
    lines.extend(f"- [{entry.date}] {entry.text}" for entry in evicted)
    return "\n".join(lines) + "\n"


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
