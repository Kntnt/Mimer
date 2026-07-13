"""The failure log: the single place every detached process reports to, so
"detached" never means "unobservable" (ADR 0011).

The log is surfaced back to the user by ``mimer-manage health``, so every message
is run through the redaction pass here before it reaches the file — each writer
benefits without having to remember (issue #24). That pass is secret-shape-based:
it strips recognised secret shapes, not arbitrary personal data or memory prose,
so callers must still log identifiers and exception types rather than raw content.
The log's owner-only file mode (0o600) is the backstop for anything that is not a
recognised secret shape.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from mimer.paths import LOG_FILENAME, store_root
from mimer.redaction import redact
from mimer.store import FILE_MODE


def log_failure(message: str, *, root: Path | None = None) -> None:
    """Append one timestamped line to the failure log.

    The message is redacted before it is written, so a recognised secret shape
    that reached a caller — an exception repr embedding pre-redaction content, say
    — cannot leak through the log the health command surfaces. Redaction is
    shape-based, so it does not strip non-secret personal data or memory prose;
    callers must not pass raw memory content (log an identifier or exception type
    instead). Newlines are then flattened so a single failure is always a single
    physical line, keeping the log grep-able. Assumes the store already exists (its
    creation is :func:`mimer.store.ensure_store`'s job).

    Args:
        message: A description of what went wrong.
        root: Store root; defaults to :func:`mimer.paths.store_root`.
    """

    root = root or store_root()

    # Strip recognised secrets before the message reaches the log: it is
    # echoed back by `mimer-manage health`, so it must not quote a secret.
    safe = redact(message)

    timestamp = datetime.now(UTC).isoformat()
    line = f"{timestamp}\t{safe}".replace("\n", " ").replace("\r", " ")

    # Append with an explicit owner-only creation mode. ensure_store normally
    # seeds mimer.log at FILE_MODE first, but this runs from capture's last-resort
    # handler, which can fire before ensure_store — a recreated log must still be
    # 0600, never the umask default (issue #26).
    fd = os.open(root / LOG_FILENAME, os.O_WRONLY | os.O_APPEND | os.O_CREAT, FILE_MODE)
    try:
        os.write(fd, (line + "\n").encode("utf-8"))
    finally:
        os.close(fd)


def fresh_failures(root: Path | None = None, *, within_hours: int = 24) -> list[str]:
    """Return failure messages logged within the last ``within_hours``.

    Used to surface a one-line health notice at session start (Stage 8). Lines
    with an unparseable timestamp are ignored. Each surfaced message is redacted
    again on read: the log file is user-writable and may hold legacy lines written
    before write-time redaction existed, so redaction is enforced at every boundary
    that echoes the log back (issue #24).
    """

    path = (root or store_root()) / LOG_FILENAME
    if not path.exists():
        return []

    cutoff = datetime.now(UTC) - timedelta(hours=within_hours)
    fresh = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stamp, _, message = line.partition("\t")
        when = _parse_stamp(stamp)
        if when is not None and when >= cutoff:
            fresh.append(redact(message))
    return fresh


def _parse_stamp(stamp: str) -> datetime | None:
    """Parse a log timestamp as an aware UTC datetime, or None when unparseable.

    Every line log_failure writes carries an aware UTC stamp, but a legacy or
    hand-written line may carry a naive one (no offset). A naive stamp parses
    fine and only trips later, when it is compared to the aware cutoff — a
    TypeError that, surfaced through the session-start health notice, would
    suppress all memory injection for the session. So a naive stamp is assumed to
    be UTC rather than allowed to crash the read: one bad line must never take
    injection down (#40).
    """

    try:
        when = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    return when if when.tzinfo is not None else when.replace(tzinfo=UTC)
