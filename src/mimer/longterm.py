"""Long-term memory: the project-scoped, append-only chronological record of
what happened, kept as one Markdown file per day. Capture appends extractive
entries here; the session digest (#7) and git reader (#14) add to it too.

A small per-project capture ledger records which turns have already been
captured, so a double-fired Stop hook cannot record a turn twice — and it lives
in a plain file, surviving even an index-free store (ADR 0011).
"""

from __future__ import annotations

from pathlib import Path

from mimer.paths import store_root
from mimer.registry import project_dir
from mimer.storeio import append_text

LONG_TERM_DIRNAME = "long-term"
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


def _ledger_path(project_id: str, root: Path | None = None) -> Path:
    return long_term_dir(project_id, root) / CAPTURE_LEDGER_FILENAME


def is_captured(project_id: str, turn_id: str, root: Path | None = None) -> bool:
    """Whether a turn has already been captured for this project."""

    path = _ledger_path(project_id, root)
    if not path.exists():
        return False
    return turn_id in path.read_text(encoding="utf-8").split()


def record_captured(project_id: str, turn_id: str, root: Path | None = None) -> None:
    """Record that a turn has been captured (append-only ledger)."""

    append_text(_ledger_path(project_id, root), turn_id)
