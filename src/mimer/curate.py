"""Curated writes (Stage 2): the memory skill's deterministic engine.

Every write reads the whole of short-term memory first (so a re-``remember``
updates rather than duplicates), then adds, replaces or removes an entry under
the per-project store lock, and echoes what happened in one line. ``forget`` is
the soft tier of ADR 0012 — it removes the entry, retracts any matching permanent
Concept, and writes a tombstone (so recall, the manifest and the injected profile
all filter the fact out), while the raw long-term record is untouched. An over-cap
write drives distillation: durable entries are
promoted into permanent memory before transient entries age out to the daily log
— promote-then-evict (ADR 0017).

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

from mimer.bundle import concept_identity_text, list_concepts, retract_concept
from mimer.distill import distill_durable_entries
from mimer.erasure import erase_from_raw_record
from mimer.longterm import append_entry
from mimer.matcher import is_same_fact
from mimer.paths import store_root
from mimer.project import confirm_hint, resolve
from mimer.redaction import redact as strip_secrets
from mimer.shortterm import (
    SHORT_TERM_CAP,
    Entry,
    aged_out_block,
    ensure_short_term,
    evict_transient,
    parse_short_term,
    render_short_term,
    short_term_path,
)
from mimer.storeio import project_lock, update_file, write_atomic
from mimer.tombstones import write_tombstone

# Curated writes land in the Notes section by default.
CURATED_SECTION = "Notes"


@dataclass(frozen=True)
class WriteResult:
    """The outcome of one curated write: what happened, the echo, a warning, the
    slugs of any durable entries the cap promoted into permanent memory, and any
    transient entries that aged out to the daily log."""

    action: str
    echo: str
    warning: str | None = None
    aged_out: tuple[str, ...] = ()
    promoted: tuple[str, ...] = ()


def _key(text: str) -> str:
    """Exact normalised identity of a fact, for the remember dedup only.

    This is deliberately *not* the shared "same fact?" matcher (issue #18). That
    matcher answers whether a fact has been forgotten across layers, and errs
    toward matching so a forget stays a forget. Remember asks a narrower, opposite
    question — is the user re-stating the one note they are editing? — where fuzzy
    overlap is unsafe: it would silently overwrite a distinct-but-similar note. So
    remember dedups on exact wording (up to case and whitespace) and leaves the
    fuzzy semantics to the three forgetting sites.
    """

    return " ".join(text.lower().split())


def remember(
    text: str,
    *,
    project_id: str,
    root: Path | None = None,
    section: str = CURATED_SECTION,
    cap: int = SHORT_TERM_CAP,
    today: date | None = None,
    durable: bool = True,
) -> WriteResult:
    """Add ``text`` to short-term memory, updating in place if already present.

    A curated write is ``durable`` by default: the user explicitly asked Mimer to
    remember it and it passed the skill's salience judgment, so it is knowledge
    worth promoting to permanent memory. Only ``durable=False`` entries — the
    digest's auto-refreshed working state and bootstrap's orientation note — age
    out into the daily log (ADR 0017).

    When a write pushes short-term over the cap, the cap drives distillation
    (ADR 0017): durable entries are promoted into permanent Concepts *first* —
    each evicted only after its Concept is verified on disk — and only then are
    transient entries aged out (oldest first) into the daily log to reach the cap.
    Promoting before evicting frees room, so a transient entry an evict-first path
    would have dropped survives. Only when a durable promotion fails and transient
    eviction alone cannot clear the cap does the write warn and keep everything.

    A secret the user or agent asks to remember is stripped here at the sink, so
    the redaction guarantee holds independently of the agent's judgment.
    """

    # Enforce redaction at the sink: dedup, storage and any eviction all operate
    # on the redacted text, so a secret never lands in short-term memory nor is
    # carried forward when a durable entry is later distilled (issue #23).
    text = strip_secrets(text)

    root = root or store_root()
    today = today or date.today()
    ensure_short_term(project_id, root)
    path = short_term_path(project_id, root)

    # Add or update the entry under the lock. The cap-driven promote-then-evict
    # runs afterwards, outside this lock: distillation takes the same per-project
    # lock and flock is not re-entrant across separate open descriptions.
    with project_lock(project_id, root=root):
        sections = parse_short_term(path.read_text(encoding="utf-8"))
        entries = sections[section]

        # Dedup: update an existing entry rather than adding a duplicate.
        key = _key(text)
        index = next((i for i, entry in enumerate(entries) if _key(entry.text) == key), None)
        entry = Entry(today.isoformat(), text, durable)
        if index is None:
            entries.insert(0, entry)
            action = "added"
        else:
            entries[index] = entry
            action = "updated"

        write_atomic(path, render_short_term(project_id, sections))
        total = sum(len(section_entries) for section_entries in sections.values())
        has_durable = any(
            e.durable for section_entries in sections.values() for e in section_entries
        )

    # Promote-then-evict when the write went over the cap: distil durable entries
    # into permanent memory (each removed only once its Concept is on disk), then
    # age transient entries out under the lock until short-term is back at the cap.
    promoted: tuple[str, ...] = ()
    evicted: list[Entry] = []
    warning: str | None = None
    if total > cap:
        if has_durable:
            results = distill_durable_entries(project_id, root=root, today=today)
            promoted = tuple(result.slug for result in results if result.slug is not None)
        with project_lock(project_id, root=root):
            sections = parse_short_term(path.read_text(encoding="utf-8"))
            evicted = evict_transient(sections, cap)
            if evicted:
                append_entry(project_id, today.isoformat(), aged_out_block(evicted, today), root)
            write_atomic(path, render_short_term(project_id, sections))
            remaining = sum(len(section_entries) for section_entries in sections.values())
            warning = (
                f"short-term memory is over its cap ({remaining}/{cap}); one or more durable "
                "entries could not be promoted (their distillation failed and was logged), and "
                "transient eviction alone could not clear the cap."
                if remaining > cap
                else None
            )

    verb = "remembered" if action == "added" else "updated"
    echo = f'Mimer: {verb} "{text}" in short-term memory (project "{project_id}").'
    if promoted:
        echo += f" Promoted {len(promoted)} durable entry(ies) to permanent memory."
    if evicted:
        echo += f" Aged out {len(evicted)} transient entry(ies) to the daily log."
    return WriteResult(action, echo, warning, tuple(e.text for e in evicted), promoted)


def _remove_matching_from_short_term(text: str, *, project_id: str, root: Path) -> int:
    """Remove every short-term entry the shared matcher judges the same fact as
    ``text``, under the project lock. Returns how many entries were removed.

    Shared by the soft (``forget``) and hard (``redact``) tiers so they agree on
    what "the fact" is and neither can diverge from the other (issue #18).
    """

    removed = 0

    def transform(content: str) -> str:
        nonlocal removed
        sections = parse_short_term(content)
        for name, entries in sections.items():
            kept = [e for e in entries if not is_same_fact(e.text, text)]
            removed += len(entries) - len(kept)
            sections[name] = kept
        return render_short_term(project_id, sections)

    update_file(short_term_path(project_id, root), transform, project_id=project_id, root=root)
    return removed


def _retract_matching_concepts(text: str, *, project_id: str, root: Path) -> list[str]:
    """Retract every permanent Concept the shared matcher judges the same fact as
    ``text``, so a forget reaches permanent memory (ADR 0012, issue #32). Returns
    the titles of the retracted Concepts.

    Scoped to Concepts whose origin is this project — the origin-keyed rule recall
    and the injection paths suppress by (ADR 0013) — so a forget never reaches into
    another project's permanent memory. Matching is on the same title+body text
    recall indexes (:func:`mimer.bundle.concept_identity_text`), so a Concept that
    would be recalled or injected for this fact is exactly the one retracted.

    Shared by the soft (``forget``) and hard (``redact``) tiers so redact stays a
    true superset of forget and neither leaves a Concept the other would retract.
    """

    retracted = []
    for concept in list_concepts(root):
        identity = concept_identity_text(concept.title, concept.body)
        if concept.origin == project_id and is_same_fact(identity, text):
            retract_concept(concept.slug, root)
            retracted.append(concept.title)
    return retracted


def forget(
    text: str, *, project_id: str, root: Path | None = None, today: date | None = None
) -> WriteResult:
    """Soft-forget ``text``: remove matching entries and write a tombstone."""

    root = root or store_root()
    ensure_short_term(project_id, root)

    # Strip secrets before matching and tombstoning so a forget targets the same
    # secret-free form remember stored, and no raw secret is persisted to the
    # durable tombstone ledger (issue #23).
    text = strip_secrets(text)

    removed = _remove_matching_from_short_term(text, project_id=project_id, root=root)
    retracted = _retract_matching_concepts(text, project_id=project_id, root=root)
    write_tombstone(text, project_id=project_id, root=root, tier="forget")

    if removed:
        action = "removed"
        echo = (
            f'Mimer: forgot "{text}" — removed from short-term memory and tombstoned so it '
            "will not resurface. The raw long-term record is untouched; run redact to erase it."
        )
    else:
        action = "tombstoned"
        echo = (
            f'Mimer: nothing in short-term memory matched "{text}", but it was tombstoned so it '
            "will not resurface. The raw long-term record is untouched."
        )
    if retracted:
        echo += f" Retracted {len(retracted)} matching permanent concept(s)."
    return WriteResult(action, echo)


def redact(
    text: str, *, project_id: str, root: Path | None = None, today: date | None = None
) -> WriteResult:
    """Hard-forget ``text``: everything :func:`forget` does, then erase the raw record.

    Redact is a superset of forget (ADR 0012): it removes matching entries from
    short-term memory and writes a tombstone (so recall and re-distillation stay
    suppressed), then additionally rewrites the append-only daily logs and the
    archived transcripts in place, replacing the fact's span with a redaction
    marker, and reindexes so the purged content no longer surfaces. It is also how
    a secret captured before the storage-time redaction pass is scrubbed.

    Short-term removal and the tombstone operate on the secret-stripped form (to
    align with what remember stored and keep the ledger secret-free — issue #23),
    while the raw-record erasure matches ``text`` verbatim as the caller names it,
    so a leaked secret still sitting raw in the record is found and erased.
    """

    root = root or store_root()
    ensure_short_term(project_id, root)

    stripped = strip_secrets(text)
    _remove_matching_from_short_term(stripped, project_id=project_id, root=root)
    _retract_matching_concepts(stripped, project_id=project_id, root=root)
    write_tombstone(stripped, project_id=project_id, root=root, tier="redact")
    erase_from_raw_record(text, project_id=project_id, root=root)

    echo = (
        f'Mimer: redacted "{stripped}" — removed from short-term memory, tombstoned, and erased '
        "from the raw long-term logs and transcripts, then reindexed. Content exported or backed "
        "up before now is beyond Mimer's reach."
    )
    return WriteResult("redacted", echo)


def _build_parser() -> argparse.ArgumentParser:
    """The ``mimer-memory`` command-line interface used by the memory skill."""

    parser = argparse.ArgumentParser(
        prog="mimer-memory", description="Curated writes to Mimer's short-term memory."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for verb in ("remember", "note", "forget", "redact"):
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
        print(
            "Mimer: this directory's project identity needs confirmation; no write "
            f"performed. {confirm_hint(resolution.candidate_id)}"
        )
        return 1

    if args.command == "forget":
        result = forget(args.text, project_id=resolution.project_id)
    elif args.command == "redact":
        result = redact(args.text, project_id=resolution.project_id)
    else:
        result = remember(args.text, project_id=resolution.project_id)

    print(result.echo)
    if result.warning:
        print(f"Mimer: {result.warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
