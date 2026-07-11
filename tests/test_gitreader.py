"""Tests for git as a capture source (Stage 6): commit messages fold into
long-term memory with `git:<sha>` provenance and a quoted excerpt, redacted and
idempotent, and the excerpt survives a history rewrite (ADR 0003).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from mimer.gitreader import fold_git_log
from mimer.index import reindex, search
from mimer.longterm import daily_log_path
from mimer.project import resolve
from mimer.store import ensure_store
from tests.gitutil import init_repo


def _project(store_root: Path, cwd: Path) -> str:
    resolution = resolve(cwd, root=store_root)
    assert resolution.project_id is not None
    return resolution.project_id


def _commit(repo: Path, message: str) -> str:
    subprocess.run(
        ["git", "-C", str(repo), "commit", "--allow-empty", "-q", "-m", message], check=True
    )
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()


def test_commit_message_recalled_and_cited(store_root: Path, tmp_path: Path) -> None:
    """A recent commit's message is recalled, cited with its git:<sha>."""

    ensure_store(store_root)
    repo = init_repo(
        tmp_path / "repo", remotes={"origin": "git@github.com:x/repo.git"}, commit=True
    )
    sha = _commit(repo, "Add the streaming parser for OKF knowledge bundles")
    pid = _project(store_root, repo)

    fold_git_log(pid, repo, root=store_root)
    reindex(store_root)

    hits = search("streaming parser for bundles", root=store_root, project_id=pid)
    assert hits
    assert any(f"git:{sha}" in c.text or f"git:{sha}" in c.heading for c in hits)
    assert any("streaming parser" in c.text for c in hits)


def test_excerpt_survives_a_history_rewrite(store_root: Path, tmp_path: Path) -> None:
    """After a history rewrite the excerpt still checks out though the SHA is gone."""

    ensure_store(store_root)
    repo = init_repo(tmp_path / "repo", commit=True)
    sha = _commit(repo, "Ship the distinctive-phrase feature xyzzy")
    pid = _project(store_root, repo)
    fold_git_log(pid, repo, root=store_root)

    # Rewrite history and prune so the folded SHA truly no longer resolves.
    subprocess.run(
        ["git", "-C", str(repo), "commit", "--amend", "--allow-empty", "-q", "-m", "Rewritten"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "reflog", "expire", "--expire=now", "--all"], check=True
    )
    subprocess.run(["git", "-C", str(repo), "gc", "--prune=now", "--quiet"], check=True)
    gone = subprocess.run(["git", "-C", str(repo), "cat-file", "-e", sha], capture_output=True)

    assert gone.returncode != 0, "expected the original SHA to be gone after the rewrite"
    stored = daily_log_path(pid, _commit_date(repo), store_root)
    # The stored excerpt survives even though the SHA is unresolvable.
    assert any("xyzzy" in log.read_text() for log in stored.parent.glob("*.md"))


def test_rerunning_the_reader_adds_nothing(store_root: Path, tmp_path: Path) -> None:
    """Re-running the git reader is idempotent."""

    ensure_store(store_root)
    repo = init_repo(tmp_path / "repo", commit=True)
    _commit(repo, "A single meaningful commit")
    pid = _project(store_root, repo)

    first = fold_git_log(pid, repo, root=store_root)
    second = fold_git_log(pid, repo, root=store_root)

    assert first >= 1
    assert second == 0


def test_secret_in_commit_message_never_stored(store_root: Path, tmp_path: Path) -> None:
    """A secret in a commit message is redacted before it reaches the store."""

    ensure_store(store_root)
    repo = init_repo(tmp_path / "repo", commit=True)
    secret = "AKIA" + "IOSFODNN7" + "EXAMPLE"
    _commit(repo, f"Wire up deploy with key {secret}")
    pid = _project(store_root, repo)

    fold_git_log(pid, repo, root=store_root)

    stored = "".join(
        log.read_text() for log in daily_log_path(pid, "2026-07-11", store_root).parent.glob("*.md")
    )
    assert secret not in stored
    assert "REDACTED" in stored


def test_non_git_project_is_skipped_cleanly(store_root: Path, tmp_path: Path) -> None:
    """A non-git project folds nothing and does not error."""

    ensure_store(store_root)
    plain = tmp_path / "plain"
    plain.mkdir()
    pid = _project(store_root, plain)

    assert fold_git_log(pid, plain, root=store_root) == 0


def _commit_date(repo: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "log", "-1", "--format=%aI"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()[:10]
