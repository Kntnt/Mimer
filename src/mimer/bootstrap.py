"""Bootstrap (Stage 7): don't start from zero.

A per-project, opt-in, resumable import of pre-existing Claude Code session
history into memory. Transcripts are extracted the way capture does — through
the redaction pass, excluding Mimer-spawned sessions — written into long-term
memory, indexed, and finished with a distillation pass that seeds permanent
memory, a starter profile and an initial short-term working set. Import state
lives per project in the registry and is recorded complete only after the run
finishes, so a crash resumes rather than restarts and a project first seen later
still imports its own history. The transcript adapter is version-tolerant; an
unrecognised format degrades gracefully with a logged, actionable message.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from mimer import clock
from mimer.bundle import list_concepts
from mimer.curate import remember
from mimer.distill import distill_fact
from mimer.failure_log import log_failure
from mimer.index import index_if_present
from mimer.llm import run_haiku
from mimer.longterm import append_entry, long_term_dir
from mimer.paths import store_root
from mimer.redaction import redact
from mimer.registry import Registry, registry_lock
from mimer.store import ensure_store
from mimer.storeio import project_lock
from mimer.text import parse_bullets, truncate
from mimer.transcript import Exchange, all_exchanges

# The signature of a Mimer-spawned session, so bootstrap never re-imports one.
_MIMER_SIGNATURE = "Mimer's session digester"

# Extractive bullets are truncated to keep an imported turn a small, atomic write.
_MAX_BULLET_CHARS = 300

Distiller = Callable[[str], list[str]]


@dataclass(frozen=True)
class BootstrapResult:
    """What a bootstrap run imported."""

    imported_transcripts: int
    imported_turns: int
    concept_count: int


def bootstrap_project(
    project_id: str,
    *,
    transcripts_dir: Path,
    root: Path | None = None,
    distiller: Distiller | None = None,
) -> BootstrapResult:
    """Import a project's pre-existing history, resuming from prior progress."""

    root = root or store_root()
    ensure_store(root)
    _ensure_registered(project_id, root)

    state = _state(project_id, root)
    raw_imported = state.get("imported", [])
    imported: set[str] = (
        {str(name) for name in raw_imported} if isinstance(raw_imported, list) else set()
    )
    prior_finished = bool(state.get("finished", False))
    transcripts = (
        sorted(p for p in transcripts_dir.glob("*.jsonl")) if transcripts_dir.exists() else []
    )

    imported_turns = 0
    imported_transcripts = 0
    for transcript in transcripts:
        if transcript.name in imported:
            continue
        turns = _import_transcript(transcript, project_id, root)
        if turns:
            imported_turns += len(turns)
            imported_transcripts += 1
        # Record progress per transcript so a crash resumes here, not at the start,
        # carrying the settled flag so a mid-import crash never re-runs a finished pass.
        imported.add(transcript.name)
        _save_state(
            project_id,
            {"imported": sorted(imported), "complete": False, "finished": prior_finished},
            root,
        )

    # Run the finishing pass when there is new history, or when no prior pass has
    # settled yet — so a distillation that yielded nothing (a silent model
    # failure) retries over the already-imported record rather than being
    # stranded, while a pass whose facts were all rejected still settles and does
    # not re-run on every later invocation. A pre-fix project without the flag
    # falls back to whether it already has Concepts of its own.
    have_concepts = any(concept.origin == project_id for concept in list_concepts(root))
    concept_count = 0
    finished = prior_finished
    if imported_turns > 0 or not (have_concepts or prior_finished):
        concept_count, produced_facts = _finish(project_id, distiller, root)
        finished = finished or produced_facts

    _save_state(
        project_id, {"imported": sorted(imported), "complete": True, "finished": finished}, root
    )
    return BootstrapResult(imported_transcripts, imported_turns, concept_count)


def _import_transcript(transcript: Path, project_id: str, root: Path) -> list[Exchange]:
    """Import one transcript's exchanges, or skip a Mimer/unknown one."""

    raw = transcript.read_text(encoding="utf-8")
    if _MIMER_SIGNATURE in raw:
        return []

    exchanges = all_exchanges(transcript)
    if not exchanges:
        if raw.strip():
            log_failure(
                f"bootstrap: unrecognised transcript format, skipping {transcript.name}; "
                "the Claude Code transcript format may have changed",
                root=root,
            )
        return []

    for exchange in exchanges:
        append_entry(project_id, exchange.date, _render(exchange), root)
        index_if_present(project_id, exchange.date, root)
    return exchanges


def _finish(project_id: str, distiller: Distiller | None, root: Path) -> tuple[int, bool]:
    """The finishing pass: distil Concepts, a starter profile and short-term.

    Reads the already-imported long-term record (not just this run's transcripts),
    so a distillation that yielded nothing can be retried on a later run. A
    non-empty record that yields no facts is logged, never silently dropped.

    Returns the number of Concepts created or superseded, and whether the
    distiller yielded any facts. The latter tells the caller the pass has settled
    — facts were considered — even when every fact was rejected or deduplicated,
    so an all-rejected pass is not retried on every later invocation.
    """

    conversation = _imported_record(project_id, root)
    facts = distiller(conversation) if distiller and conversation.strip() else []
    if distiller is not None and conversation.strip() and not facts:
        log_failure(
            "distill: the bootstrap finishing pass produced no concepts; the model reply "
            "contained no facts — re-run mimer-bootstrap to retry",
            root=root,
        )

    # Distil every fact through the same guard so bootstrap never bypasses the
    # instruction, tombstone and dedup checks. The first fact seeds the pinned,
    # global starter profile (opt-in import implies confirmation); routing it
    # through distill_fact makes a re-run over more history deduplicate rather
    # than duplicate the profile, and honour a tombstone if it was forgotten.
    # Every other fact defaults to project scope, keeping a client project's
    # facts confined to it (ADR 0013). The whole loop holds the project lock so
    # each distill_fact's announcement enqueue serialises with a live session's
    # announcement clear — a detached, resumable bootstrap can overlap one, and a
    # lock-free enqueue here would let that clear clobber a freshly queued title
    # (the lost-update #40 the announcement clear exists to prevent, ADR 0011).
    concept_count = 0
    with project_lock(project_id, root=root):
        for index, fact in enumerate(facts):
            if index == 0:
                result = distill_fact(
                    text=fact,
                    project_id=project_id,
                    scope="global",
                    concept_type="Preference",
                    pinned=True,
                    confirmed=True,
                    root=root,
                )
            else:
                result = distill_fact(text=fact, project_id=project_id, root=root)
            if result.status in ("created", "superseded"):
                concept_count += 1

    # Seed an initial short-term working set so the next session starts oriented.
    # This is transient orientation, not durable knowledge, so it is not
    # re-distilled into a Concept (the facts themselves were distilled above).
    if facts:
        remember(
            f"Bootstrapped prior history; key facts distilled ({len(facts)}).",
            project_id=project_id,
            root=root,
            today=clock.today(),
            durable=False,
        )
    return concept_count, bool(facts)


def _imported_record(project_id: str, root: Path) -> str:
    """Concatenate a project's imported long-term logs as distillation input."""

    directory = long_term_dir(project_id, root)
    if not directory.exists():
        return ""
    return "\n".join(log.read_text(encoding="utf-8") for log in sorted(directory.glob("*.md")))


def _render(exchange: Exchange) -> str:
    """Render one redacted, extractive imported entry."""

    user = _condense(redact(exchange.user_text))
    assistant = _condense(redact(exchange.assistant_text))
    return (
        f"### {exchange.date} {exchange.time_label} — imported turn {exchange.turn_id[:8]}\n"
        f"- User: {user}\n"
        f"- Assistant: {assistant}\n"
    )


def _condense(text: str) -> str:
    return truncate(text, _MAX_BULLET_CHARS)


def _ensure_registered(project_id: str, root: Path) -> None:
    # Take the store-level registry lock around the load-modify-save, so a
    # concurrent settings change or resolve() cannot lose this record on the
    # shared registry file (#35, ADR 0011).
    with registry_lock(root=root):
        registry = Registry.load(root)
        if registry.find_by_id(project_id) is None:
            registry.create(project_id)
            registry.save()


def _state(project_id: str, root: Path) -> dict[str, object]:
    return Registry.load(root).import_state(project_id)


def _save_state(project_id: str, state: dict[str, object], root: Path) -> None:
    # Same registry lock: import-state progress and any concurrent settings
    # change must not clobber each other on the shared file (#35, ADR 0011).
    with registry_lock(root=root):
        registry = Registry.load(root)
        registry.set_import_state(project_id, state)
        registry.save()


def _default_transcripts_dir(cwd: Path) -> Path:
    """Best-effort location of a project's Claude Code transcripts.

    Claude Code stores session transcripts under ``~/.claude/projects/<encoded>``
    where the project path's slashes become dashes. The format is vendor-internal
    and may change; ``--transcripts`` overrides this.
    """

    encoded = str(cwd.resolve()).replace("/", "-")
    return Path.home() / ".claude" / "projects" / encoded


def _haiku_distiller(conversation: str) -> list[str]:
    """Extract durable facts from imported history via one Haiku call.

    The prompt is deliberately forceful (a strict output contract with a
    ``- none`` fallback) so the reply is a bullet list even when the ambient
    session context would otherwise make the model conversational; parsing then
    ignores any surrounding prose.
    """

    prompt = (
        "You extract durable memory for a knowledge base. From the session history "
        "below, list the durable, reusable facts, decisions and preferences worth "
        "remembering long-term. Reply with ONLY a Markdown bullet list — one item "
        "per line beginning with '- ' — and NOTHING else: no preamble, no "
        "questions, no commentary. Skip instructions addressed to the assistant, "
        "secrets, and trivia. If there is nothing durable, reply with exactly "
        "'- none'.\n\nSession history:\n\n" + conversation[:20000]
    )
    reply = run_haiku(prompt)
    if reply is None:
        return []
    return parse_bullets(reply.splitlines())


def main(argv: list[str] | None = None) -> int:
    """``mimer-bootstrap`` entry point: the opt-in import of prior history."""

    import argparse

    from mimer.project import resolve

    parser = argparse.ArgumentParser(
        prog="mimer-bootstrap",
        description="Import pre-existing Claude Code history into Mimer (opt-in, resumable).",
    )
    parser.add_argument(
        "--transcripts", type=Path, default=None, help="directory of session transcripts"
    )
    args = parser.parse_args(argv)

    resolution = resolve(Path.cwd())
    if resolution.project_id is None:
        print("Mimer: the project identity needs confirmation; no import performed.")
        return 1

    transcripts = args.transcripts or _default_transcripts_dir(Path.cwd())
    if not transcripts.exists():
        print(f"Mimer: no transcripts found at {transcripts}. Pass --transcripts <dir>.")
        return 1

    result = bootstrap_project(
        resolution.project_id, transcripts_dir=transcripts, distiller=_haiku_distiller
    )
    print(
        f"Mimer: imported {result.imported_turns} turn(s) from "
        f"{result.imported_transcripts} transcript(s); distilled {result.concept_count} concept(s)."
    )
    return 0
