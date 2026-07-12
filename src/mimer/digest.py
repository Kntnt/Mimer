"""The session digest (Stage 3b): the one batched Haiku call per session.

At session end Mimer sends the redacted conversation to Haiku once (ADR 0009) and
uses the reply to (1) append a session digest to the daily log, (2) refresh
short-term memory's auto-maintained sections so the next snapshot is current for
users who never say "remember", and (3) archive the redacted transcript as
provenance. When headless Claude is unavailable the extractive record stands, the
digest defers, and the failure log says so. The run is idempotent per session.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from mimer import llm
from mimer.failure_log import log_failure
from mimer.index import index_if_present
from mimer.longterm import append_entry, is_digested, record_digested, transcripts_dir
from mimer.paths import safe_identifier, store_root
from mimer.project import resolve
from mimer.redaction import redact
from mimer.shortterm import (
    AUTO_REFRESHED_SECTIONS,
    Entry,
    ensure_short_term,
    parse_short_term,
    render_short_term,
)
from mimer.store import FILE_MODE
from mimer.storeio import project_lock, write_atomic
from mimer.transcript import conversation_text

Haiku = Callable[[str], str | None]


@dataclass(frozen=True)
class DigestResult:
    """The outcome of a digest attempt."""

    status: str
    archive_path: Path | None = None


def digest_session(
    payload: Mapping[str, Any],
    *,
    root: Path | None = None,
    haiku: Haiku | None = None,
    today: date | None = None,
) -> DigestResult:
    """Digest a session described by a SessionEnd payload. Never raises."""

    root = root or store_root()
    today = today or date.today()
    call_haiku = haiku or llm.run_haiku

    try:
        cwd = Path(payload.get("cwd") or ".")
        transcript_path = payload.get("transcript_path")
        session_id = str(payload.get("session_id") or "")

        # Reject a traversal- or otherwise malformed session id before any store
        # write, so a bad id fails the whole digest cleanly instead of first
        # mutating the daily log and short-term and only tripping later when it
        # would become the archive path (#25).
        safe_identifier(session_id or "session", kind="session id")

        resolution = resolve(cwd, root=root)
        project_id = resolution.project_id
        if project_id is None:
            return DigestResult("skipped-identity")
        if not transcript_path:
            return DigestResult("nothing")
        if is_digested(project_id, session_id, root):
            return DigestResult("duplicate")

        transcript = Path(transcript_path)
        conversation = conversation_text(transcript)
        if not conversation.strip():
            return DigestResult("nothing")

        # The one model call, on the redacted conversation. A None reply means
        # headless Claude is unavailable — defer, leaving the extractive record.
        reply = call_haiku(_build_prompt(redact(conversation)))
        if reply is None:
            log_failure("digest deferred: headless Claude unavailable", root=root)
            return DigestResult("deferred")

        digest, active, pending = _parse_reply(reply)

        # Re-check and persist as one serialised unit under the project lock — the
        # way capture already does — so two SessionEnd runs racing on this session
        # (a retry, a crash-and-refire, overlapping events) digest it at most once
        # instead of each appending its own block. The Haiku call above stays
        # outside the lock; holding it across a ~120s model call would wedge the
        # store for every other session.
        with project_lock(project_id, root=root):
            if is_digested(project_id, session_id, root):
                return DigestResult("duplicate")
            _append_digest(project_id, today, digest, root)
            _refresh_short_term(project_id, active, pending, today, root)
            archive_path = _archive_transcript(project_id, session_id, transcript, root)
            record_digested(project_id, session_id, root)

        # Keep the derived index in step, when one exists (ADR 0011).
        index_if_present(project_id, today.isoformat(), root)
        return DigestResult("digested", archive_path)

    except Exception as exc:  # noqa: BLE001 - the digest must never crash the session
        log_failure(f"digest: {exc!r}", root=root)
        return DigestResult("failed")


def _build_prompt(conversation: str) -> str:
    """Build the digester prompt requesting a fixed, parseable reply format."""

    return (
        "You are Mimer's session digester. Summarise the following coding session "
        "for a future session's memory. Reply in EXACTLY this format, with these "
        "three headings and nothing else:\n\n"
        "## Digest\n<2-4 sentences on what happened and what was decided>\n\n"
        "## Active threads\n- <one ongoing thread per line, or '- none'>\n\n"
        "## Pending decisions\n- <one open decision per line, or '- none'>\n\n"
        "Session transcript:\n\n" + conversation
    )


def _parse_reply(reply: str) -> tuple[str, list[str], list[str]]:
    """Parse the Haiku reply into (digest text, active threads, pending decisions)."""

    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in reply.splitlines():
        if line.startswith("## "):
            current = line[3:].strip().lower()
            sections[current] = []
        elif current is not None:
            sections[current].append(line)

    digest = "\n".join(sections.get("digest", [])).strip()
    return (
        digest,
        _bullets(sections.get("active threads", [])),
        _bullets(sections.get("pending decisions", [])),
    )


def _bullets(lines: list[str]) -> list[str]:
    """Extract non-empty, non-'none' bullet texts from a block of lines."""

    texts = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("- "):
            text = stripped[2:].strip()
            if text and text.lower() != "none":
                texts.append(text)
    return texts


def _append_digest(project_id: str, today: date, digest: str, root: Path) -> None:
    """Append the session digest to today's daily log."""

    if not digest:
        return
    entry = f"## Session digest ({datetime.now().strftime('%H:%M')})\n\n{digest}\n"
    append_entry(project_id, today.isoformat(), entry, root)


def _refresh_short_term(
    project_id: str, active: list[str], pending: list[str], today: date, root: Path
) -> None:
    """Rewrite the auto-maintained short-term sections from the digest.

    The caller already holds the project lock, so the file is read and rewritten
    directly with ``write_atomic``; re-locking via ``update_file`` would deadlock
    on the same per-project advisory lock.
    """

    # Replace each auto-maintained section wholesale with today's digest lines,
    # leaving the curated sections (Notes) untouched.
    path = ensure_short_term(project_id, root)
    sections = parse_short_term(path.read_text(encoding="utf-8"))
    sections[AUTO_REFRESHED_SECTIONS[0]] = [Entry(today.isoformat(), text) for text in active]
    sections[AUTO_REFRESHED_SECTIONS[1]] = [Entry(today.isoformat(), text) for text in pending]
    write_atomic(path, render_short_term(project_id, sections))


def _archive_transcript(project_id: str, session_id: str, transcript: Path, root: Path) -> Path:
    """Archive the redacted transcript as provenance (not indexed).

    ``session_id`` is already validated as a bare identifier by ``digest_session``
    before any store write, so it is a safe filename component here (#25).
    """

    archive_dir = transcripts_dir(project_id, root)
    archive_dir.mkdir(mode=0o700, parents=True, exist_ok=True)

    archive_path = archive_dir / f"{session_id or 'session'}.jsonl"
    archive_path.write_text(redact(transcript.read_text(encoding="utf-8")), encoding="utf-8")
    archive_path.chmod(FILE_MODE)
    return archive_path
