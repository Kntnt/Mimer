"""Drive Mimer's hooks as Claude Code does: a subprocess reading a JSON payload
on stdin and answering on stdout with an exit code.

The harness invokes the exact console entry points declared in
``pyproject.toml`` (``mimer-session-start`` and friends), resolved from the
active virtualenv's ``bin`` directory so the test never depends on ``PATH``.
This keeps the tests faithful to the real hook contract while staying fast
enough for the concurrency stress cases in later tickets.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from coverage import Coverage

# Maps a Claude Code hook event name to the console script that services it.
HOOK_EXECUTABLES = {
    "SessionStart": "mimer-session-start",
    "Stop": "mimer-stop",
    "SessionEnd": "mimer-session-end",
}

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PYPROJECT = _REPO_ROOT / "pyproject.toml"


def subprocess_coverage_env() -> dict[str, str]:
    """Environment that makes a hook subprocess measure its own coverage.

    Mimer's hooks run almost entirely in the subprocesses spawned below, so
    without this the coverage report counts that code — most of Mimer's real
    behaviour — as unrun. Coverage's auto-installed startup ``.pth`` calls
    ``process_startup`` when ``COVERAGE_PROCESS_START`` is set, which reads the
    project's ``[tool.coverage]`` config (parallel mode) and starts measuring;
    ``COVERAGE_FILE`` points each child's data file at the parent's, next to
    which pytest-cov combines everything at the end.

    Returns an empty mapping when the parent is not running under coverage, so a
    plain ``pytest`` run leaves no stray ``.coverage.*`` files behind.
    """

    if Coverage.current() is None:
        return {}

    # Match the parent's data-file location so the combine step finds the
    # children's parallel data. pytest-cov defaults to ``.coverage`` at the repo
    # root, fixed when it initialised; an explicit COVERAGE_FILE overrides it.
    data_file = os.environ.get("COVERAGE_FILE") or str(_REPO_ROOT / ".coverage")
    return {
        "COVERAGE_PROCESS_START": str(_PYPROJECT),
        "COVERAGE_FILE": str(Path(data_file).resolve()),
    }


@dataclass(frozen=True)
class HookResult:
    """The observable outcome of one hook invocation."""

    returncode: int
    stdout: str
    stderr: str


def hook_command(event: str) -> list[str]:
    """Resolve the console entry point for a hook event to an absolute path.

    Resolving next to ``sys.executable`` finds the script inside the same
    virtualenv pytest is running under, independent of ``PATH``.
    """

    executable = Path(sys.executable).parent / HOOK_EXECUTABLES[event]
    return [str(executable)]


def run_hook(
    event: str,
    payload: dict[str, Any] | str,
    *,
    store_root: Path,
    cwd: Path | None = None,
    guard: bool = False,
    extra_env: dict[str, str] | None = None,
    timeout: float = 60.0,
) -> HookResult:
    """Invoke a hook as a subprocess with ``payload`` on stdin.

    Args:
        event: The Claude Code event name (``SessionStart``, ``Stop``,
            ``SessionEnd``).
        payload: A dict serialised to JSON, or a raw string sent verbatim (used
            to exercise malformed input).
        store_root: The isolated store root, passed via ``MIMER_HOME`` so the
            real ``~/.mimer`` is never touched.
        cwd: Working directory for the subprocess; defaults to the caller's.
        guard: When true, sets the re-entrancy guard env var.
        extra_env: Additional environment overrides.
        timeout: Seconds before the call is abandoned.
    """

    # Build an environment isolated to the test's store; the guard var is
    # cleared unless explicitly requested so a stray parent value cannot leak.
    env = {**os.environ, "MIMER_HOME": str(store_root)}
    env.pop("MIMER_GUARD", None)
    if guard:
        env["MIMER_GUARD"] = "1"

    # Let the child measure its own coverage when the run is under coverage;
    # a caller's extra_env still wins, so tests can point a child elsewhere.
    env.update(subprocess_coverage_env())
    if extra_env:
        env.update(extra_env)

    stdin = payload if isinstance(payload, str) else json.dumps(payload)
    completed = subprocess.run(
        hook_command(event),
        input=stdin,
        text=True,
        capture_output=True,
        env=env,
        cwd=str(cwd) if cwd is not None else None,
        timeout=timeout,
    )
    return HookResult(completed.returncode, completed.stdout, completed.stderr)


def session_start_payload(*, source: str = "startup", cwd: str = "/tmp/project") -> dict[str, Any]:
    """A representative SessionStart stdin payload."""

    return {
        "session_id": "test-session",
        "transcript_path": "/tmp/transcript.jsonl",
        "cwd": cwd,
        "hook_event_name": "SessionStart",
        "source": source,
    }


def stop_payload(*, cwd: str = "/tmp/project") -> dict[str, Any]:
    """A representative Stop stdin payload."""

    return {
        "session_id": "test-session",
        "transcript_path": "/tmp/transcript.jsonl",
        "cwd": cwd,
        "hook_event_name": "Stop",
        "stop_hook_active": False,
    }


def session_end_payload(*, reason: str = "other", cwd: str = "/tmp/project") -> dict[str, Any]:
    """A representative SessionEnd stdin payload."""

    return {
        "session_id": "test-session",
        "transcript_path": "/tmp/transcript.jsonl",
        "cwd": cwd,
        "hook_event_name": "SessionEnd",
        "reason": reason,
    }
