"""Curated writes (Stage 2): the memory skill's deterministic engine.

Every write reads the whole of short-term memory first (so a re-``remember``
updates rather than duplicates), then adds, replaces or removes an entry under
the per-project store lock, and echoes what happened in one line. ``forget`` is
the soft tier of ADR 0012 — removal plus a tombstone; the raw long-term record
is untouched. The cap only warns at this stage; eviction arrives with capture
(ADR 0017).

The judgment of *when* to call each operation — salience, durability, and
disambiguation such as "forget about X for now" (defer, do not delete) — lives
as editable prose in the memory skill (``skills/memory/SKILL.md``, ADR 0018),
not here.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from mimer.paths import store_root
from mimer.project import resolve
from mimer.shortterm import (
    SHORT_TERM_CAP,
    Entry,
    ensure_short_term,
    parse_short_term,
    render_short_term,
    short_term_path,
)
from mimer.storeio import update_file
from mimer.tombstones import write_tombstone

# Curated writes land in the Notes section by default.
CURATED_SECTION = "Notes"


@dataclass(frozen=True)
class WriteResult:
    """The outcome of one curated write: what happened, the user echo, a warning."""

    action: str
    echo: str
    warning: str | None = None


def _key(text: str) -> str:
    """A normalised identity for a fact, so dedup ignores trivial wording."""

    return " ".join(text.lower().split())


def remember(
    text: str,
    *,
    project_id: str,
    root: Path | None = None,
    section: str = CURATED_SECTION,
    cap: int = SHORT_TERM_CAP,
    today: date | None = None,
) -> WriteResult:
    """Add ``text`` to short-term memory, updating in place if already present."""

    root = root or store_root()
    today = today or date.today()
    ensure_short_term(project_id, root)

    outcome: dict[str, str | None] = {}

    def transform(content: str) -> str:
        sections = parse_short_term(content)
        entries = sections[section]

        # Dedup: update an existing entry rather than adding a duplicate.
        key = _key(text)
        index = next((i for i, entry in enumerate(entries) if _key(entry.text) == key), None)
        if index is None:
            entries.insert(0, Entry(today.isoformat(), text))
            outcome["action"] = "added"
        else:
            entries[index] = Entry(today.isoformat(), text)
            outcome["action"] = "updated"

        # Cap check: warn only — nothing is evicted before capture exists.
        total = sum(len(section_entries) for section_entries in sections.values())
        outcome["warning"] = (
            f"short-term memory is over its cap ({total}/{cap}); nothing was evicted "
            "(eviction begins once capture is enabled)."
            if total > cap
            else None
        )
        return render_short_term(project_id, sections)

    update_file(short_term_path(project_id, root), transform, project_id=project_id, root=root)

    action = outcome["action"]
    verb = "remembered" if action == "added" else "updated"
    echo = f'Mimer: {verb} "{text}" in short-term memory (project "{project_id}").'
    return WriteResult(str(action), echo, outcome["warning"])


def forget(
    text: str, *, project_id: str, root: Path | None = None, today: date | None = None
) -> WriteResult:
    """Soft-forget ``text``: remove matching entries and write a tombstone."""

    root = root or store_root()
    ensure_short_term(project_id, root)

    removed = 0

    def transform(content: str) -> str:
        nonlocal removed
        sections = parse_short_term(content)

        # Remove any entry that matches or contains the target fact's identity.
        key = _key(text)
        for name, entries in sections.items():
            kept = [e for e in entries if _key(e.text) != key and key not in _key(e.text)]
            removed += len(entries) - len(kept)
            sections[name] = kept
        return render_short_term(project_id, sections)

    update_file(short_term_path(project_id, root), transform, project_id=project_id, root=root)
    write_tombstone(text, project_id=project_id, root=root, tier="forget")

    if removed:
        action = "removed"
        echo = (
            f'Mimer: forgot "{text}" — removed from short-term memory and tombstoned so it '
            "will not resurface. The raw long-term record is untouched (use redact to erase it)."
        )
    else:
        action = "tombstoned"
        echo = (
            f'Mimer: nothing in short-term memory matched "{text}", but it was tombstoned so it '
            "will not resurface. The raw long-term record is untouched."
        )
    return WriteResult(action, echo)


def _build_parser() -> argparse.ArgumentParser:
    """The ``mimer-memory`` command-line interface used by the memory skill."""

    parser = argparse.ArgumentParser(
        prog="mimer-memory", description="Curated writes to Mimer's short-term memory."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for verb in ("remember", "note", "forget"):
        subparser = subparsers.add_parser(verb)
        subparser.add_argument("text")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Resolve the current project and perform one curated write, echoing it."""

    args = _build_parser().parse_args(argv)

    # Resolve from the invocation's working directory; an unconfirmed identity
    # never writes memory.
    resolution = resolve(Path.cwd())
    if resolution.project_id is None:
        print("Mimer: this directory's project identity needs confirmation; no write performed.")
        return 1

    if args.command == "forget":
        result = forget(args.text, project_id=resolution.project_id)
    else:
        result = remember(args.text, project_id=resolution.project_id)

    print(result.echo)
    if result.warning:
        print(f"Mimer: {result.warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
