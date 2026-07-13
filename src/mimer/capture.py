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
from mimer.pause import is_paused
from mimer.project import resolve
from mimer.redaction import redact
from mimer.registry import Registry
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
        # A paused session records nothing, whichever project it is in (#35).
        if is_paused(root):
            return CaptureResult("paused")

        cwd = Path(payload.get("cwd") or ".")
        transcript_path = payload.get("transcript_path")

        # Resolve the project; an unconfirmed identity captures nothing.
        resolution = resolve(cwd, root=root)
        if resolution.project_id is None:
            return CaptureResult("skipped-identity")

        # A project with capture turned off records nothing (ADR 0013).
        if not Registry.load(root).capture_enabled(resolution.project_id):
            return CaptureResult("capture-disabled")

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

        # The capture is durable now — the entry is in the daily log and the
        # ledger — so index upkeep is a separate, best-effort step: index
        # contention is not a capture failure (see _index_or_log).
        _index_or_log(project_id, exchange.date, root)
        return CaptureResult("captured", exchange.turn_id, exchange.date)

    except Exception as exc:  # noqa: BLE001 - capture must never raise to the session
        # Log the exception type, never its repr: the repr can quote the exchange
        # being processed before redaction ran, and log_failure's shape-based pass
        # cannot strip non-secret memory prose or PII from the health-surfaced log (#24).
        log_failure(f"capture: {type(exc).__name__}", root=root)
        return CaptureResult("failed")


def _index_or_log(project_id: str, day: str, root: Path) -> None:
    """Keep the derived index in step with the just-written entry, non-fatally.

    The daily-log entry is already durable when this runs and the index is
    derived and rebuildable (ADR 0011), so index trouble — a concurrent writer
    hitting the busy timeout, most typically — is benign contention, not a
    capture failure. Flipping an already-recorded capture to "failed" over it
    would mislead the caller, and raising a health warning over it would be the
    spurious-failure symptom of #40. So any failure here is swallowed rather than
    raised into capture's broad handler, and logged non-fatally: it stays visible
    to ``mimer-manage health`` for observability but does not trip the session-start
    health notice (see :func:`mimer.failure_log.fresh_failures`).
    """

    try:
        index_if_present(project_id, day, root)
    except Exception as exc:  # noqa: BLE001 - index upkeep is best-effort, not the capture
        log_failure(f"capture: index update failed: {type(exc).__name__}", root=root, fatal=False)


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
        # Read and parse the spool inside the same logging guard the rest of
        # capture uses. This process is detached with stderr routed to DEVNULL, so
        # a corrupt or unreadable spool raising here would vanish with no trace —
        # breaking the module's "every failure is logged" contract (#40).
        # capture_from_payload has its own broad handler and never raises.
        payload = json.loads(spool.read_text(encoding="utf-8"))
        capture_from_payload(payload)
    except Exception as exc:  # noqa: BLE001 - a detached capture must never fail silently
        log_failure(f"capture: spool read failed: {type(exc).__name__}", root=store_root())
    finally:
        spool.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
