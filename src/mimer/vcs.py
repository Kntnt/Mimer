"""Thin, failure-tolerant wrappers over the ``git`` CLI, used by project-identity
resolution. Every function treats "not a git repository" (and a missing ``git``)
as a normal, empty answer rather than an error, because non-git projects are
first-class (ADR 0008).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Commit:
    """The identifying facts of a single commit, for a git citation (ADR 0021).

    ``subject`` is the commit's first line — the checkable excerpt that survives a
    history rewrite even after ``sha`` becomes stale. ``date`` is the committer
    date in ISO ``YYYY-MM-DD`` form.
    """

    sha: str
    subject: str
    date: str


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


def head_commit(cwd: Path) -> Commit | None:
    """The repository's HEAD commit, or None outside a repo or on any git error.

    Reactive and lightweight (ADR 0021): a single ``git log -1`` at HEAD, never a
    walk of history. Returns None for a non-git directory, a repository with no
    HEAD yet, a missing ``git`` binary or any other git failure, so the caller can
    treat "no commit to cite" uniformly — no citation, never a crash.

    The three fields — full sha, subject and committer date — are read in one call,
    delimited by the ASCII unit separator so a subject bearing any ordinary
    punctuation still splits cleanly. Output that does not parse into the three
    fields is treated as no commit, keeping the failure mode uniform.
    """

    output = _run_git(cwd, "log", "-1", "--format=%H%x1f%s%x1f%cs")
    if not output:
        return None

    parts = output.split("\x1f")
    if len(parts) != 3 or not parts[0]:
        return None
    sha, subject, commit_date = parts
    return Commit(sha=sha, subject=subject, date=commit_date)
