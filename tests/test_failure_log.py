"""Tests for the failure log: it is surfaced back to the user by
``mimer-manage health``, so it must never become a back door around the redaction
guarantee. Every message is run through the redaction pass before it reaches the
file (issue #24).

Secrets are assembled from fragments at runtime so no complete secret literal is
committed to the repository (GitHub push protection scans file contents);
``log_failure`` still receives the fully-assembled strings.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from mimer.failure_log import fresh_failures, log_failure
from mimer.paths import LOG_FILENAME
from mimer.store import ensure_store


def _aws_key() -> str:
    return "AKIA" + "IOSFODNN7" + "EXAMPLE"


def test_log_failure_redacts_secret_before_writing(store_root: Path) -> None:
    """A secret embedded in a failure message never reaches the log file."""

    ensure_store(store_root)
    secret = _aws_key()

    log_failure(f"capture: boom while handling {secret}", root=store_root)

    contents = (store_root / LOG_FILENAME).read_text(encoding="utf-8")
    assert secret not in contents
    assert "REDACTED" in contents


def test_fresh_failures_redacts_legacy_unredacted_line(store_root: Path) -> None:
    """A secret-bearing line written before write-time redaction existed is still
    not surfaced verbatim: fresh_failures redacts on read (issue #24)."""

    ensure_store(store_root)
    secret = _aws_key()

    # Simulate a legacy line written directly, bypassing log_failure's redaction.
    timestamp = datetime.now(UTC).isoformat()
    (store_root / LOG_FILENAME).write_text(
        f"{timestamp}\tdistill: promotion failed for {secret}\n", encoding="utf-8"
    )

    surfaced = fresh_failures(store_root)

    assert surfaced
    assert all(secret not in message for message in surfaced)


def test_naive_timestamp_line_does_not_suppress_injection(store_root: Path) -> None:
    """A failure line with a naive (offset-less) timestamp is still surfaced rather
    than raising a TypeError. The naive stamp parses fine, so the crash used to
    come from comparing it to the aware cutoff — and, surfaced through the health
    notice, that one bad line suppressed all memory injection for the session (#40)."""

    ensure_store(store_root)

    # A naive stamp: the current UTC instant rendered with its offset stripped, so
    # it is unambiguously fresh yet carries no tzinfo.
    naive_stamp = datetime.now(UTC).replace(tzinfo=None).isoformat()
    (store_root / LOG_FILENAME).write_text(
        f"{naive_stamp}\tcapture: boom\n", encoding="utf-8"
    )

    surfaced = fresh_failures(store_root)

    assert any("boom" in message for message in surfaced)
