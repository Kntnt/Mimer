"""Helpers for building throwaway git repositories in tests, so project-identity
resolution is exercised against real ``git`` output rather than mocks.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _git(cwd: Path, *args: str) -> str:
    """Run a git command in ``cwd`` and return its stdout."""

    result = subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
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


def commit(repo: Path, message: str, *, allow_empty: bool = True) -> str:
    """Make a commit with ``message`` in ``repo`` and return its full sha.

    ``allow_empty`` lets a test plant a commit with a distinctive subject without
    staging any change — the subject is the checkable excerpt a git citation quotes.
    """

    args = ["commit", "-q", "-m", message]
    if allow_empty:
        args.insert(1, "--allow-empty")
    _git(repo, *args)
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
