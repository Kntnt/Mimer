"""Extractive capture (Stage 3a): the Stop hook's fire-and-forget recorder.

Per assistant turn, the last exchange is extracted from the transcript, run
through the redaction pass, condensed into extractive bullets — no model call
(ADR 0009) — and appended to today's daily log, keyed by the turn's own
timestamp. The write is idempotent on (project id, turn identity) via a durable
ledger, taken under the per-project lock so concurrent captures never collide.
Every failure is logged; nothing is ever raised to the session.

Invoked directly by the Stop hook (which spawns it detached), and unit-testable
as :func:`capture_from_payload`.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mimer.failure_log import log_failure
from mimer.index import index_if_present
from mimer.longterm import append_entry, is_captured, record_captured
from mimer.paths import store_root
from mimer.project import resolve
from mimer.redaction import redact
from mimer.storeio import project_lock
from mimer.transcript import Exchange, last_exchange

# Extractive bullets are truncated so a captured turn stays a small, atomic write.
_MAX_BULLET_CHARS = 300


@dataclass(frozen=True)
class CaptureResult:
    """The outcome of a capture attempt, for tests and callers."""

    status: str
    turn_id: str | None = None
    day: str | None = None


def capture_from_payload(payload: Mapping[str, Any], *, root: Path | None = None) -> CaptureResult:
    """Capture the last exchange described by a Stop-hook payload.

    Returns a result describing what happened; never raises. A failure is written
    to the failure log, and any prior daily-log entries are left intact.
    """

    root = root or store_root()

    try:
        cwd = Path(payload.get("cwd") or ".")
        transcript_path = payload.get("transcript_path")

        # Resolve the project; an unconfirmed identity captures nothing.
        resolution = resolve(cwd, root=root)
        if resolution.project_id is None:
            return CaptureResult("skipped-identity")
        if not transcript_path:
            return CaptureResult("nothing-to-capture")

        exchange = last_exchange(Path(transcript_path))
        if exchange is None:
            return CaptureResult("nothing-to-capture")

        # Dedup-and-append atomically under the project lock, so a double fire or
        # a concurrent session cannot record the same turn twice or lose a write.
        project_id = resolution.project_id
        with project_lock(project_id, root=root):
            if is_captured(project_id, exchange.turn_id, root):
                return CaptureResult("duplicate", exchange.turn_id, exchange.date)
            append_entry(project_id, exchange.date, _render_entry(exchange), root)
            record_captured(project_id, exchange.turn_id, root)

        # Keep the derived index in step, when one exists (ADR 0011).
        index_if_present(project_id, exchange.date, root)
        return CaptureResult("captured", exchange.turn_id, exchange.date)

    except Exception as exc:  # noqa: BLE001 - capture must never raise to the session
        # Log the exception type, never its repr: the repr can quote the exchange
        # being processed before redaction ran, and log_failure's shape-based pass
        # cannot strip non-secret memory prose or PII from the health-surfaced log (#24).
        log_failure(f"capture: {type(exc).__name__}", root=root)
        return CaptureResult("failed")


def _render_entry(exchange: Exchange) -> str:
    """Render one redacted, extractive daily-log entry for an exchange."""

    user = _condense(redact(exchange.user_text))
    assistant = _condense(redact(exchange.assistant_text))
    return (
        f"### {exchange.time_label} — turn {exchange.turn_id[:8]}\n"
        f"- User: {user}\n"
        f"- Assistant: {assistant}\n"
    )


def _condense(text: str) -> str:
    """Collapse whitespace and truncate, keeping the entry small and single-line."""

    collapsed = " ".join(text.split())
    if len(collapsed) > _MAX_BULLET_CHARS:
        return collapsed[:_MAX_BULLET_CHARS].rstrip() + "…"
    return collapsed


def main(argv: list[str] | None = None) -> int:
    """Detached entry point: read a spooled payload file, capture, then clean up.

    The Stop hook spawns this as a separate, session-detached process so capture
    never delays the session.
    """

    args = argv if argv is not None else sys.argv[1:]
    if not args:
        return 1

    spool = Path(args[0])
    try:
        payload = json.loads(spool.read_text(encoding="utf-8"))
        capture_from_payload(payload)
    finally:
        spool.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
