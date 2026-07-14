"""Opt-in integration coverage for the one real model call (ADR 0009).

Every unit test injects a fake Haiku reply, so the *success* path of
``llm.run_haiku`` — the ``claude -p --model haiku`` argv, ``check=True`` and the
stdout parsing — never runs in CI. A vendor-side flag change or a wrapped output
would then degrade the boundary pass to "deferred / no concepts" silently. This
module drives the real binary end to end.

It is skipped by default: the tests run only when ``MIMER_INTEGRATION=1`` is
set and a ``claude`` binary is reachable, so default CI needs no live binary.
"""

from __future__ import annotations

import os
import shutil
from datetime import date
from pathlib import Path

import pytest

from mimer import llm
from mimer.boundary import run_boundary_pass
from mimer.capture import capture_from_payload
from mimer.store import ensure_store

# The redacted real transcript shared with the parser coverage — a realistic
# conversation whose captured turns the boundary pass distils.
REAL_TRANSCRIPT = Path(__file__).resolve().parent / "fixtures" / "real_transcript.jsonl"

# The binary the real call would invoke, honouring the same override llm.py uses.
_CLAUDE_BIN = os.environ.get(llm.CLAUDE_BIN_ENV, "claude")

# Gate the whole module: opt in with MIMER_INTEGRATION=1 and a reachable binary.
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("MIMER_INTEGRATION") != "1" or shutil.which(_CLAUDE_BIN) is None,
        reason="opt-in: set MIMER_INTEGRATION=1 with a reachable `claude` binary on PATH",
    ),
]


def test_run_haiku_success_path_returns_trimmed_stdout() -> None:
    """The real CLI call returns its trimmed stdout, exercising the exact argv,
    ``check=True`` and stdout parsing the unit fakes bypass."""

    reply = llm.run_haiku("Reply with exactly this single lowercase word and nothing else: pong")

    assert reply is not None
    assert "pong" in reply.lower()


def test_real_boundary_pass_against_a_real_raw_record_completes(
    store_root: Path, project_dir: Path
) -> None:
    """A real Haiku boundary pass over a real captured raw record completes rather
    than deferring — the end-to-end gate on top of the fakes, exercising the exact
    ``claude -p`` argv and stdout parsing the unit fakes bypass."""

    ensure_store(store_root)
    payload = {
        "session_id": "integration-sess",
        "hook_event_name": "SessionEnd",
        "reason": "other",
        "cwd": str(project_dir),
        "transcript_path": str(REAL_TRANSCRIPT),
    }

    # Seed the raw long-term record the boundary pass distils from.
    capture_from_payload(payload, root=store_root)

    # No haiku= override, so run_boundary_pass calls the real llm.run_haiku. A
    # "completed" status is what proves the real CLI answered a non-empty, parseable
    # reply — a deferral would mean the argv or stdout parsing broke.
    result = run_boundary_pass(payload, root=store_root, today=date(2026, 6, 18))

    assert result.status == "completed", result.status
