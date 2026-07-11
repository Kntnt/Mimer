"""Helpers for building throwaway git repositories in tests, so project-identity
resolution is exercised against real ``git`` output rather than mocks.
"""

from __future__ import annotations

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
