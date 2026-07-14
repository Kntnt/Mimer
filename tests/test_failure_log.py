"""Tests for the failure log: it is surfaced back to the user by
``mimer-manage health``, so it must never become a back door around the redaction
guarantee. Every message is run through the redaction pass before it reaches the
file (issue #24).

Secrets are assembled from fragments at runtime so no complete secret literal is
committed to the repository (GitHub push protection scans file contents);
``log_failure`` still receives the fully-assembled strings.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from mimer.failure_log import NON_FATAL_PREFIX, fresh_failures, log_failure
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


def test_log_failure_redacts_on_its_own_account_before_the_write_seam(
    store_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """log_failure redacts the record itself before handing it to the write seam.

    ADR 0020 keeps every sink's redaction call as defence-in-depth and forbids
    pruning it as "redundant with the seam"; #56 deleted this one and leaned solely
    on ``storeio.append_text``'s seam redaction. Capturing the exact string handed
    to append_text — with the seam stubbed out so its own pass cannot mask a missing
    sink pass — proves log_failure redacted the secret before the seam, not only at
    it: the argument is already free of the secret and already carries the marker.
    """

    from mimer import failure_log

    ensure_store(store_root)
    secret = _aws_key()

    # Stub the write seam to record the exact string log_failure hands it, so the
    # seam's own redaction cannot stand in for the sink-level pass under test.
    captured: list[str] = []
    monkeypatch.setattr(failure_log, "append_text", lambda path, text: captured.append(text))

    log_failure(f"capture: boom while handling {secret}", root=store_root)

    assert captured
    assert secret not in captured[0]
    assert "REDACTED" in captured[0]


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
    (store_root / LOG_FILENAME).write_text(f"{naive_stamp}\tcapture: boom\n", encoding="utf-8")

    surfaced = fresh_failures(store_root)

    assert any("boom" in message for message in surfaced)


def test_non_fatal_note_is_logged_but_excluded_from_the_health_notice(store_root: Path) -> None:
    """A non-fatal note (benign index contention) lands in the log for observability
    but is skipped by fresh_failures, so it never raises the spurious session-start
    health warning a real failure would (#40)."""

    ensure_store(store_root)
    log_failure("capture: index update failed: OperationalError", root=store_root, fatal=False)
    log_failure("distill: promotion failed", root=store_root)

    surfaced = fresh_failures(store_root)

    # Only the real failure drives the health notice; the non-fatal note does not.
    assert any("promotion failed" in message for message in surfaced)
    assert all("index update failed" not in message for message in surfaced)

    # Yet the non-fatal note is still on disk, tagged, for `mimer-manage health`.
    contents = (store_root / LOG_FILENAME).read_text(encoding="utf-8")
    assert NON_FATAL_PREFIX in contents
    assert "index update failed" in contents


def test_non_fatal_note_stays_skipped_when_redaction_rewrites_the_tag(
    store_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-fatal note stays out of the health notice even when the write-seam
    redaction rewrites its tag.

    #56 routes the write through ``storeio.append_text``, which redacts the whole
    line — tag included — a second time (#55), downstream of where log_failure
    controls it. The tag survives today only because ``[non-fatal]`` happens to
    match no redaction rule; the tag-after-redaction ordering that once guaranteed
    it no longer does. fresh_failures must therefore key on the tag's *stored*
    (redacted) form, not on the literal surviving redaction — otherwise a new
    redaction rule that touches bracketed tokens (or a secret-shaped
    NON_FATAL_PREFIX) desyncs write from read and resurrects the #40
    spurious-failure, surfacing benign self-healing events as real failures at
    session start.
    """

    # Stand in for any future rule that rewrites the tag: append one that redacts
    # the non-fatal tag, so the tag no longer reaches disk verbatim.
    from mimer import redaction

    monkeypatch.setattr(
        redaction,
        "_RULES",
        [*redaction._RULES, (re.compile(re.escape(NON_FATAL_PREFIX)), "[REDACTED-TAG]")],
    )

    ensure_store(store_root)
    log_failure("capture: index update failed: OperationalError", root=store_root, fatal=False)
    log_failure("distill: promotion failed", root=store_root)

    surfaced = fresh_failures(store_root)

    # The real failure still drives the notice; the tag-rewritten non-fatal note does not.
    assert any("promotion failed" in message for message in surfaced)
    assert all("index update failed" not in message for message in surfaced)
