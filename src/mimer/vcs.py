"""Thin, failure-tolerant wrappers over the ``git`` CLI, used by project-identity
resolution. Every function treats "not a git repository" (and a missing ``git``)
as a normal, empty answer rather than an error, because non-git projects are
first-class (ADR 0008).
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def _run_git(cwd: Path, *args: str) -> str | None:
    """Run a git command in ``cwd``; return trimmed stdout, or None on any error.

    A non-zero exit (not a repository), a missing binary, or a timeout all map to
    None so callers can treat "no git information" uniformly.
    """

    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return None

    return result.stdout.strip()


def git_toplevel(cwd: Path) -> str | None:
    """Return the repository's top-level directory, or None outside a repo.

    For a linked worktree this is the worktree's own root; the shared identity of
    worktrees comes from their common remote, not this path.
    """

    return _run_git(cwd, "rev-parse", "--show-toplevel")


def git_remotes(cwd: Path) -> dict[str, str]:
    """Return a mapping of remote name to URL for the repository at ``cwd``.

    Empty when there is no repository or the repository has no remotes.
    """

    listing = _run_git(cwd, "remote")
    if not listing:
        return {}

    # Resolve each remote name to its fetch URL; skip any that fail individually.
    remotes: dict[str, str] = {}
    for name in listing.splitlines():
        url = _run_git(cwd, "remote", "get-url", name)
        if url:
            remotes[name] = url
    return remotes
