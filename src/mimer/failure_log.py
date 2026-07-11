"""The failure log: the single place every detached process reports to, so
"detached" never means "unobservable" (ADR 0011).
"""

from __future__ import annotations

from datetime import UTC, datetime
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
