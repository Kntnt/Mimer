"""Tests for the failure log: it is surfaced back to the user by
``mimer-manage health``, so it must never become a back door around the redaction
guarantee. Every message is run through the redaction pass before it reaches the
file (issue #24).

Secrets are assembled from fragments at runtime so no complete secret literal is
committed to the repository (GitHub push protection scans file contents);
``log_failure`` still receives the fully-assembled strings.
"""

from __future__ import annotations

from pathlib import Path

from mimer.failure_log import log_failure
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
