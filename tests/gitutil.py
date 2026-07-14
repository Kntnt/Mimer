"""Helpers for building throwaway git repositories in tests, so project-identity
resolution is exercised against real ``git`` output rather than mocks.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _git(cwd: Path, *args: str, env: dict[str, str] | None = None) -> str:
    """Run a git command in ``cwd`` and return its stdout.

    ``env`` replaces the process environment for this one call — used to pin a
    commit's author and committer date.
    """

    result = subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return result.stdout.strip()


def init_repo(
    path: Path,
    *,
    remotes: dict[str, str] | None = None,
    commit: bool = False,
) -> Path:
    """Create a git repository at ``path`` with optional remotes and a commit.

    Args:
        path: Directory to initialise (created if absent).
        remotes: Mapping of remote name to URL to register.
        commit: When true, make one initial commit — required before a worktree
            can be added.
    """

    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True, capture_output=True)

    # Identity and settings so commits succeed in a clean CI environment.
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test")
    _git(path, "config", "commit.gpgsign", "false")

    if remotes:
        for name, url in remotes.items():
            _git(path, "remote", "add", name, url)

    if commit:
        (path / "README.md").write_text("seed\n", encoding="utf-8")
        _git(path, "add", "-A")
        _git(path, "commit", "-q", "-m", "seed")

    return path


def add_worktree(repo: Path, worktree_path: Path) -> Path:
    """Add a linked worktree of ``repo`` at ``worktree_path`` (repo needs a commit)."""

    _git(repo, "worktree", "add", "-q", str(worktree_path))
    return worktree_path


def add_remote(repo: Path, name: str, url: str) -> None:
    """Register an additional remote on an existing repository."""

    _git(repo, "remote", "add", name, url)


def commit(repo: Path, message: str, *, allow_empty: bool = True, date: str | None = None) -> str:
    """Make a commit with ``message`` in ``repo`` and return its full sha.

    ``allow_empty`` lets a test plant a commit with a distinctive subject without
    staging any change — the subject is the checkable excerpt a git citation quotes.
    ``date`` pins the author and committer date to a chosen day (an ISO
    ``YYYY-MM-DD`` or a full timestamp), so a test can place a commit before or on
    the session day — the citation guard cites a commit only when it was made on or
    after that day (issue #66).
    """

    args = ["commit", "-q", "-m", message]
    if allow_empty:
        args.insert(1, "--allow-empty")

    # git's environment date parser rejects a bare day, so anchor a day to noon —
    # far enough from either midnight that no timezone offset rolls it to an
    # adjacent day when the committer date is read back.
    env = None
    if date is not None:
        stamp = date if "T" in date else f"{date}T12:00:00"
        env = {**os.environ, "GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp}

    _git(repo, *args, env=env)
    return _git(repo, "rev-parse", "HEAD")


def head_sha(repo: Path) -> str:
    """The full sha of the repository's current HEAD commit."""

    return _git(repo, "rev-parse", "HEAD")


def commit_subjects(repo: Path) -> list[str]:
    """Every commit subject in the repository's history, newest first."""

    output = _git(repo, "log", "--format=%s")
    return output.splitlines() if output else []


def commit_shas(repo: Path) -> list[str]:
    """Every commit sha in the repository's history, newest first."""

    output = _git(repo, "log", "--format=%H")
    return output.splitlines() if output else []


def rewrite_history(repo: Path) -> str:
    """Simulate a history rewrite: change HEAD's sha while keeping its subject.

    Amends the HEAD commit with a fixed, far-future committer and author date, so
    the commit object — and therefore its sha — changes while the subject line a
    git citation quoted is preserved. Returns the new HEAD sha. This models a
    rebase or amend that invalidates a stored ``git:<sha>`` while leaving the
    checkable excerpt intact (ADR 0021).
    """

    env = {
        **os.environ,
        "GIT_COMMITTER_DATE": "2030-01-01T00:00:00",
        "GIT_AUTHOR_DATE": "2030-01-01T00:00:00",
    }
    subprocess.run(
        ["git", "-C", str(repo), "commit", "--amend", "--no-edit", "--allow-empty"],
        check=True,
        capture_output=True,
        env=env,
    )
    return _git(repo, "rev-parse", "HEAD")
