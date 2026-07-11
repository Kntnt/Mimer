"""The one model call Mimer makes: a guarded, headless Claude Haiku invocation
(ADR 0009).

Mimer reuses the user's existing Claude access through the Claude Code CLI
(``claude -p --model haiku``) rather than a stored API key. The call carries the
re-entrancy guard, so any Mimer hooks the spawned session fires exit at once and
it can never capture itself. When the CLI is unavailable, the call returns None
and the caller degrades gracefully — never a crash, never a stored credential.
"""

from __future__ import annotations

import os
import subprocess

from mimer.guard import spawn_env

# The Claude CLI binary, overridable for tests and unusual installs.
CLAUDE_BIN_ENV = "MIMER_CLAUDE_BIN"

# A single batched call should never hang the session close for long.
DEFAULT_TIMEOUT_SECONDS = 120


def run_haiku(prompt: str, *, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> str | None:
    """Run one headless Haiku call with ``prompt`` on stdin; return its text.

    Returns None when the CLI is missing, errors, times out or answers empty —
    the signal for the caller to defer to the next opportunity.
    """

    binary = os.environ.get(CLAUDE_BIN_ENV, "claude")

    try:
        completed = subprocess.run(
            [binary, "-p", "--model", "haiku"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=spawn_env(),
            check=True,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None

    answer = completed.stdout.strip()
    return answer or None
