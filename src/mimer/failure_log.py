"""The failure log: the single place every detached process reports to, so
"detached" never means "unobservable" (ADR 0011).

The log is surfaced back to the user by ``mimer-manage health``, so every message
is run through the redaction pass at storeio's write seam before it reaches the
file — each writer benefits without having to remember (issue #24, #56). That pass
is secret-shape-based: it strips recognised secret shapes, not arbitrary personal
data or memory prose, so callers must still log identifiers and exception types
rather than raw content. The log's owner-only file mode (0o600) is the backstop for
anything that is not a recognised secret shape.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from mimer.paths import LOG_FILENAME, store_root
from mimer.redaction import redact
from mimer.storeio import append_text

# The severity tag a non-fatal note carries at the head of its message. It keeps
# the log a single grep-able column while letting the session-start health notice
# tell benign, self-healing trouble (index contention over a rebuildable index)
# from a real failure, so a routine busy-timeout no longer raises a spurious
# warning — yet the note still lands in the log `mimer-manage health` surfaces, so
# it stays observable (#40).
NON_FATAL_PREFIX = "[non-fatal]"


def log_failure(message: str, *, root: Path | None = None, fatal: bool = True) -> None:
    """Append one timestamped line to the failure log.

    Newlines are flattened so a single failure is always a single physical line,
    keeping the log grep-able, and the record is appended through storeio's
    ``O_APPEND`` primitive. That primitive redacts the whole line at the write seam
    (ADR 0020) before bytes reach disk, so a recognised secret shape that reached a
    caller — an exception repr embedding pre-redaction content, say — cannot leak
    through the log the health command surfaces. Redaction is shape-based, so it
    does not strip non-secret personal data or memory prose; callers must not pass
    raw memory content (log an identifier or exception type instead). append_text
    also creates the store directory and the log itself owner-only when absent, so a
    failure logged before :func:`mimer.store.ensure_store` has run — as capture's
    last-resort handler can — still lands 0600 (issue #26).

    Args:
        message: A description of what went wrong.
        root: Store root; defaults to :func:`mimer.paths.store_root`.
        fatal: Whether this is a real failure. A non-fatal note — benign,
            self-healing trouble such as index contention over a rebuildable
            index — is still logged and surfaced by ``mimer-manage health``, but
            tagged so :func:`fresh_failures` skips it and the session-start health
            notice does not raise a spurious warning over it (#40).
    """

    root = root or store_root()

    # Tag a non-fatal note so fresh_failures can skip it. Redaction is not applied
    # here: append_text redacts the whole line at the write seam (ADR 0020), so the
    # message and this tag are stripped there, once. The tag is therefore run
    # through the redaction pass along with everything else — the tag-after-redaction
    # ordering that once shielded it is gone — so fresh_failures keys on the tag's
    # redacted form rather than trusting the literal to survive the pass unchanged.
    tagged = message if fatal else f"{NON_FATAL_PREFIX} {message}"

    # Frame the record as a single grep-able physical line — the timestamp, then
    # the message with newlines flattened — and append it through storeio's
    # O_APPEND primitive (ADR 0011's write-discipline map), which redacts the line
    # and creates a missing log owner-only, so a log recreated before ensure_store
    # runs — this can fire from capture's last-resort handler, ahead of it — is
    # still 0600, never the umask default (issue #26).
    timestamp = datetime.now(UTC).isoformat()
    line = f"{timestamp}\t{tagged}".replace("\n", " ").replace("\r", " ")
    append_text(root / LOG_FILENAME, line)


def fresh_failures(root: Path | None = None, *, within_hours: int = 24) -> list[str]:
    """Return real failure messages logged within the last ``within_hours``.

    Used to surface a one-line health notice at session start (Stage 8). Lines
    with an unparseable timestamp are ignored, and non-fatal notes are skipped —
    detected by the tag's redacted form, since append_text redacts the whole line
    at rest (#55, #56), so the raw ``[non-fatal]`` literal is not guaranteed to
    survive that pass. A benign, self-healing event (index contention over a
    rebuildable index) is logged for observability but must not raise a health
    warning indistinguishable from a real failure — the spurious-failure symptom of
    #40. ``mimer-manage health`` reads the log directly, so those notes stay visible
    there. Each surfaced message is redacted again on read: the log file is
    user-writable and may hold legacy lines written before write-time redaction
    existed, so redaction is enforced at every boundary that echoes the log back
    (issue #24).
    """

    path = (root or store_root()) / LOG_FILENAME
    if not path.exists():
        return []

    cutoff = datetime.now(UTC) - timedelta(hours=within_hours)

    # The non-fatal tag as it survives the write pass: append_text redacts the
    # whole line (ADR 0020), tag included, so the tag reaches disk in its redacted
    # form. Key on that form, not on the raw NON_FATAL_PREFIX literal, so a change
    # to the prefix or a new redaction rule that rewrites the tag cannot desync
    # write from read and resurrect the #40 spurious-failure (a benign self-healing
    # event surfaced as a real one). Today the two forms coincide — the tag matches
    # no rule — so this changes nothing until redaction touches the tag.
    stored_non_fatal_prefix = redact(NON_FATAL_PREFIX)

    fresh = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stamp, _, message = line.partition("\t")
        when = _parse_stamp(stamp)
        if when is not None and when >= cutoff and not message.startswith(stored_non_fatal_prefix):
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
