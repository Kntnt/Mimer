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
from datetime import date
from pathlib import Path

from mimer.bundle import create_concept
from mimer.curate import remember
from mimer.distill import _title, distill_fact
from mimer.failure_log import log_failure
from mimer.index import index_if_present
from mimer.longterm import append_entry
from mimer.paths import store_root
from mimer.redaction import redact
from mimer.registry import Registry
from mimer.store import ensure_store
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

    raw_imported = _state(project_id, root).get("imported", [])
    imported: set[str] = (
        {str(name) for name in raw_imported} if isinstance(raw_imported, list) else set()
    )
    transcripts = (
        sorted(p for p in transcripts_dir.glob("*.jsonl")) if transcripts_dir.exists() else []
    )

    imported_turns = 0
    imported_transcripts = 0
    conversation_parts: list[str] = []
    for transcript in transcripts:
        if transcript.name in imported:
            continue
        turns = _import_transcript(transcript, project_id, root)
        if turns:
            imported_turns += len(turns)
            imported_transcripts += 1
            conversation_parts.extend(f"{e.user_text}\n{e.assistant_text}" for e in turns)
        # Record progress per transcript so a crash resumes here, not at the start.
        imported.add(transcript.name)
        _save_state(project_id, {"imported": sorted(imported), "complete": False}, root)

    concept_count = _finish(project_id, "\n".join(conversation_parts), distiller, root)
    _save_state(project_id, {"imported": sorted(imported), "complete": True}, root)
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


def _finish(project_id: str, conversation: str, distiller: Distiller | None, root: Path) -> int:
    """The finishing pass: distil Concepts, a starter profile and short-term."""

    facts = distiller(conversation) if distiller and conversation.strip() else []

    concept_count = 0
    for index, fact in enumerate(facts):
        if index == 0:
            # The first fact seeds the pinned starter profile (opt-in import
            # implies confirmation).
            create_concept(
                title=_title(fact),
                body=fact,
                concept_type="Preference",
                origin=project_id,
                scope="global",
                pinned=True,
                confirmed=True,
                root=root,
            )
        else:
            distill_fact(text=fact, project_id=project_id, scope="global", root=root)
        concept_count += 1

    # Seed an initial short-term working set so the next session starts oriented.
    if facts:
        remember(
            f"Bootstrapped prior history; key facts distilled ({len(facts)}).",
            project_id=project_id,
            root=root,
            today=date.today(),
        )
    return concept_count


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
    collapsed = " ".join(text.split())
    if len(collapsed) > _MAX_BULLET_CHARS:
        return collapsed[:_MAX_BULLET_CHARS].rstrip() + "…"
    return collapsed


def _ensure_registered(project_id: str, root: Path) -> None:
    registry = Registry.load(root)
    if registry.find_by_id(project_id) is None:
        registry.create(project_id)
        registry.save()


def _state(project_id: str, root: Path) -> dict[str, object]:
    return Registry.load(root).import_state(project_id)


def _save_state(project_id: str, state: dict[str, object], root: Path) -> None:
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
    """Extract durable facts from imported history via one Haiku call."""

    from mimer.llm import run_haiku

    prompt = (
        "Extract the durable, reusable facts, decisions and preferences worth "
        "remembering from this history — one per line as '- fact'. Skip "
        "instructions to the assistant, secrets, and trivia.\n\n" + conversation[:20000]
    )
    reply = run_haiku(prompt)
    if reply is None:
        return []
    return [
        line.strip()[2:].strip()
        for line in reply.splitlines()
        if line.strip().startswith("- ") and len(line.strip()) > 3
    ]


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
