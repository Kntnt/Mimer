"""Long-term memory: the project-scoped, append-only chronological record of
what happened, kept as one Markdown file per day. Capture appends the extractive
turns here; the session-boundary pass distils from this raw record but never
writes an abstractive block back to it — the raw log stays raw (ADR 0023).

One small per-project dedup ledger backs idempotency: the capture ledger records
which turns have been captured, so a double-fired Stop hook cannot record a turn
twice. It is a bounded window of recent ids in a plain file, surviving even an
index-free store — see :mod:`mimer.ledger` (ADR 0011, #41). The boundary pass
needs no such ledger: distillation is idempotent per fact (ADR 0015), so
re-reading the raw record mints no duplicates.
"""

from __future__ import annotations

from pathlib import Path

from mimer.ledger import Ledger
from mimer.paths import store_root
from mimer.registry import project_dir
from mimer.storeio import append_text

LONG_TERM_DIRNAME = "long-term"
TRANSCRIPTS_DIRNAME = "transcripts"
CAPTURE_LEDGER_FILENAME = ".capture-ledger"


def long_term_dir(project_id: str, root: Path | None = None) -> Path:
    """The directory holding a project's daily long-term logs."""

    return project_dir(project_id, root or store_root()) / LONG_TERM_DIRNAME


def daily_log_path(project_id: str, day: str, root: Path | None = None) -> Path:
    """The daily long-term log for ``day`` (``YYYY-MM-DD``) in a project."""

    return long_term_dir(project_id, root) / f"{day}.md"


def append_entry(project_id: str, day: str, entry: str, root: Path | None = None) -> None:
    """Append one entry to a project's daily log (atomic ``O_APPEND``)."""

    append_text(daily_log_path(project_id, day, root), entry)


def _capture_ledger(project_id: str, root: Path | None = None) -> Ledger:
    return Ledger(long_term_dir(project_id, root) / CAPTURE_LEDGER_FILENAME)


def is_captured(project_id: str, turn_id: str, root: Path | None = None) -> bool:
    """Whether a turn is still inside the project's recent-capture window."""

    return _capture_ledger(project_id, root).contains(turn_id)


def record_captured(project_id: str, turn_id: str, root: Path | None = None) -> None:
    """Record that a turn has been captured (under the caller's project lock)."""

    _capture_ledger(project_id, root).record(turn_id)


def transcripts_dir(project_id: str, root: Path | None = None) -> Path:
    """The directory holding a project's archived (redacted) transcripts."""

    return project_dir(project_id, root or store_root()) / TRANSCRIPTS_DIRNAME
