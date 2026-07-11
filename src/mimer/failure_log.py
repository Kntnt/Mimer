"""The failure log: the single place every detached process reports to, so
"detached" never means "unobservable" (ADR 0011).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from mimer.paths import LOG_FILENAME, store_root


def log_failure(message: str, *, root: Path | None = None) -> None:
    """Append one timestamped line to the failure log.

    Newlines in ``message`` are flattened so a single failure is always a single
    physical line, keeping the log grep-able. Assumes the store already exists
    (its creation is :func:`mimer.store.ensure_store`'s job).

    Args:
        message: A description of what went wrong.
        root: Store root; defaults to :func:`mimer.paths.store_root`.
    """

    root = root or store_root()

    timestamp = datetime.now(UTC).isoformat()
    line = f"{timestamp}\t{message}".replace("\n", " ").replace("\r", " ")
    with (root / LOG_FILENAME).open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def fresh_failures(root: Path | None = None, *, within_hours: int = 24) -> list[str]:
    """Return failure messages logged within the last ``within_hours``.

    Used to surface a one-line health notice at session start (Stage 8). Lines
    with an unparseable timestamp are ignored.
    """

    path = (root or store_root()) / LOG_FILENAME
    if not path.exists():
        return []

    cutoff = datetime.now(UTC) - timedelta(hours=within_hours)
    fresh = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stamp, _, message = line.partition("\t")
        try:
            when = datetime.fromisoformat(stamp)
        except ValueError:
            continue
        if when >= cutoff:
            fresh.append(message)
    return fresh
