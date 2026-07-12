"""Integration tests for ticket #1: hooks fire as JSON-in/JSON-out subprocesses,
the store bootstraps with owner-only permissions, the re-entrancy guard short-
circuits without touching the store, and simulated failures are observable.
"""

from __future__ import annotations

import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tests.harness import (
    run_hook,
    session_end_payload,
    session_start_payload,
    stop_payload,
)

EVENTS = [
    ("SessionStart", session_start_payload),
    ("Stop", stop_payload),
    ("SessionEnd", session_end_payload),
]


@pytest.mark.parametrize("event, make_payload", EVENTS)
def test_each_hook_runs_as_noop_and_exits_zero(
    event: str,
    make_payload: Callable[[], dict[str, Any]],
    store_root: Path,
    project_dir: Path,
) -> None:
    """Every registered hook runs as a clean no-op that exits 0."""

    result = run_hook(event, make_payload(), store_root=store_root, cwd=project_dir)

    assert result.returncode == 0, result.stderr


def test_first_invocation_creates_store_with_permissions(
    store_root: Path, project_dir: Path
) -> None:
    """The first hook invocation creates the store and failure log with
    0700 directories and 0600 files."""

    assert not store_root.exists()

    result = run_hook(
        "SessionStart", session_start_payload(), store_root=store_root, cwd=project_dir
    )

    assert result.returncode == 0, result.stderr
    assert store_root.is_dir()
    assert stat.S_IMODE(store_root.stat().st_mode) == 0o700
    log = store_root / "mimer.log"
    assert log.is_file()
    assert stat.S_IMODE(log.stat().st_mode) == 0o600
    assert log.read_text() == ""


def test_guarded_hook_exits_immediately_without_touching_store(
    store_root: Path, project_dir: Path
) -> None:
    """A hook invoked under the re-entrancy guard exits 0 and creates nothing."""

    result = run_hook("Stop", stop_payload(), store_root=store_root, cwd=project_dir, guard=True)

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert not store_root.exists()


def test_malformed_payload_logs_one_failure_line(store_root: Path, project_dir: Path) -> None:
    """A simulated failure (malformed stdin) writes exactly one line to the log
    and still exits without disturbing the session."""

    result = run_hook("Stop", "this is not json", store_root=store_root, cwd=project_dir)

    assert result.returncode == 0, result.stderr
    log_lines = [ln for ln in (store_root / "mimer.log").read_text().splitlines() if ln.strip()]
    assert len(log_lines) == 1
    assert "Stop" in log_lines[0]


def test_reinvocation_preserves_failure_log(store_root: Path, project_dir: Path) -> None:
    """A second invocation neither errors nor clobbers prior failure-log lines."""

    run_hook("SessionStart", session_start_payload(), store_root=store_root, cwd=project_dir)
    log = store_root / "mimer.log"
    log.write_text("prior failure\n")

    result = run_hook(
        "SessionStart", session_start_payload(), store_root=store_root, cwd=project_dir
    )

    assert result.returncode == 0, result.stderr
    assert log.read_text() == "prior failure\n"
