"""Tests for git as a capture source (Stage 6): commit messages fold into
long-term memory with `git:<sha>` provenance and a quoted excerpt, redacted and
idempotent, and the excerpt survives a history rewrite (ADR 0003).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from mimer import gitreader
from mimer.failure_log import fresh_failures
from mimer.gitreader import fold_git_log
from mimer.index import reindex, search
from mimer.ledger import Ledger
from mimer.longterm import append_entry, daily_log_path, long_term_dir
from mimer.project import resolve
from mimer.store import ensure_store
from tests.gitutil import init_repo

# Every test here loads the embedding model (directly or via a hook subprocess),
# so the session fixture prefetches it once before the suite runs (conftest.py).
pytestmark = pytest.mark.embedding


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


def _commit_dated(repo: Path, message: str, date: str) -> str:
    """Make an empty commit whose author and committer dates are both ``date``.

    Fixing the committer date lets a test control ``git log``'s default ordering,
    which is what interleaves a merged-in branch behind mainline commits.
    """

    stamp = f"{date}T12:00:00"
    env = {**os.environ, "GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp}
    subprocess.run(
        ["git", "-C", str(repo), "commit", "--allow-empty", "-q", "-m", message],
        check=True,
        env=env,
    )
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


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


def test_first_fold_backfills_full_history_beyond_100_commits(
    store_root: Path, tmp_path: Path
) -> None:
    """First adoption of a repo with >100 prior commits folds the whole history.

    The reader used to consider only the most recent 100 commits, so anything
    older was silently and permanently absent (issue #42). A first fold now pages
    through the entire history.
    """

    ensure_store(store_root)
    repo = init_repo(tmp_path / "repo", commit=True)

    # A repository whose history is well past the old 100-commit window.
    for n in range(150):
        _commit(repo, f"Commit number {n:03d} marker-{n:03d}")
    pid = _project(store_root, repo)

    folded = fold_git_log(pid, repo, root=store_root)

    # Every commit is folded, including the oldest — far beyond the last 100.
    assert folded > 100
    stored = "".join(log.read_text() for log in long_term_dir(pid, store_root).glob("*.md"))
    assert "marker-000" in stored
    assert "marker-149" in stored

    # A history that fits within the safety bound logs no truncation notice.
    assert not fresh_failures(store_root)

    # Re-running the completed fold still adds nothing.
    assert fold_git_log(pid, repo, root=store_root) == 0


def test_first_fold_is_bounded_and_logged(
    store_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A first backfill honours a documented bound and logs the truncation.

    An enormous repository must not stall a session boundary, so the first fold
    is capped; the cap is observable in the failure log rather than silent.
    """

    # raising=False so the red demonstrates the wrong behaviour — an unbounded,
    # unlogged fold — rather than an AttributeError on a not-yet-existing symbol.
    monkeypatch.setattr(gitreader, "_FIRST_FOLD_LIMIT", 5, raising=False)
    ensure_store(store_root)
    repo = init_repo(tmp_path / "repo", commit=True)
    for n in range(20):
        _commit(repo, f"Commit number {n:03d} boundmarker-{n:03d}")
    pid = _project(store_root, repo)

    folded = fold_git_log(pid, repo, root=store_root)

    # Exactly the bound's worth of commits fold, and the truncation is logged.
    assert folded == 5
    assert any("backfill" in message for message in fresh_failures(store_root))

    # The five retained commits are the newest five, as the bound promises.
    stored = "".join(log.read_text() for log in long_term_dir(pid, store_root).glob("*.md"))
    assert all(f"boundmarker-{n:03d}" in stored for n in range(15, 20))
    assert not any(f"boundmarker-{n:03d}" in stored for n in range(15))


def test_later_fold_folds_only_the_new_commits(store_root: Path, tmp_path: Path) -> None:
    """A steady-state fold folds exactly the commits added since the previous fold.

    Exercises the incremental path directly: accumulate the not-yet-folded commits,
    then stop at the already-folded boundary. Every new commit must reach long-term
    memory and nothing that was already folded is re-added (issue #42).
    """

    ensure_store(store_root)
    repo = init_repo(tmp_path / "repo", commit=True)
    _commit(repo, "Groundwork before the first fold")
    pid = _project(store_root, repo)
    fold_git_log(pid, repo, root=store_root)

    # Three commits added above the already-folded boundary.
    shas = [_commit(repo, f"Later commit {n} latermarker-{n}") for n in range(3)]

    folded = fold_git_log(pid, repo, root=store_root)

    # Exactly the three new commits fold, each landing in long-term memory.
    assert folded == 3
    stored = "".join(log.read_text() for log in long_term_dir(pid, store_root).glob("*.md"))
    assert all(f"git:{sha}" in stored for sha in shas)


def test_merge_folds_commits_ordered_behind_a_folded_one(store_root: Path, tmp_path: Path) -> None:
    """A merge that orders new commits behind an already-folded one still folds them.

    A feature branch cut from an early commit, merged after main advanced, brings in
    commits whose commit date predates a folded mainline commit — so ``git log``
    lists them *after* it. Stopping at the first already-folded SHA would drop them
    silently and permanently (issue #42), so the reader must keep scanning.
    """

    ensure_store(store_root)
    repo = init_repo(tmp_path / "repo", commit=True)
    default_branch = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    # A feature branch is cut from an early commit, then main advances past it.
    _commit_dated(repo, "A groundwork alpha-marker", "2026-01-01")
    _git(repo, "branch", "feature")
    _commit_dated(repo, "B mainline beta-marker", "2026-01-05")
    _commit_dated(repo, "C mainline gamma-marker", "2026-01-06")
    pid = _project(store_root, repo)
    fold_git_log(pid, repo, root=store_root)

    # The feature branch's older-dated commits are merged back into main.
    _git(repo, "checkout", "-q", "feature")
    _commit_dated(repo, "F1 feature delta-marker", "2026-01-02")
    _commit_dated(repo, "F2 feature epsilon-marker", "2026-01-03")
    _git(repo, "checkout", "-q", default_branch)
    merge_env = {
        **os.environ,
        "GIT_AUTHOR_DATE": "2026-01-07T12:00:00",
        "GIT_COMMITTER_DATE": "2026-01-07T12:00:00",
    }
    subprocess.run(
        ["git", "-C", str(repo), "merge", "--no-ff", "-q", "feature", "-m", "M merge omega-marker"],
        check=True,
        env=merge_env,
    )

    folded = fold_git_log(pid, repo, root=store_root)

    # The merge commit and both feature commits fold — not just the merge commit.
    assert folded == 3
    stored = "".join(log.read_text() for log in long_term_dir(pid, store_root).glob("*.md"))
    assert "delta-marker" in stored
    assert "epsilon-marker" in stored
    assert "omega-marker" in stored


def test_merge_folds_commits_lagging_more_than_a_page_behind(
    store_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A merge whose commits lag mainline by more than a page is still fully folded.

    The steady-state reader must not treat ``git log``'s commit-date order as a stop
    signal. When a merged feature branch's old-dated commits sort more than
    ``_PAGE_SIZE`` positions below the newest new commit — a whole already-folded
    page sitting between them — a page-window heuristic returns the moment that page
    yields nothing new and drops the deeper commits silently and permanently
    (issue #42). Shrinking the page makes that lag testable without a 100-commit
    fixture, mirroring how the bound test shrinks ``_FIRST_FOLD_LIMIT``.
    """

    # A tiny page turns a handful of mainline commits into a lag exceeding one page.
    monkeypatch.setattr(gitreader, "_PAGE_SIZE", 3)
    ensure_store(store_root)
    repo = init_repo(tmp_path / "repo", commit=True)
    default_branch = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    # A feature branch is cut early, then main advances well past a single page.
    _commit_dated(repo, "A groundwork alpha-marker", "2026-01-01")
    _git(repo, "branch", "feature")
    for n in range(5):
        _commit_dated(repo, f"Mainline {n} main-marker-{n}", f"2026-02-0{n + 1}")
    pid = _project(store_root, repo)
    fold_git_log(pid, repo, root=store_root)

    # The feature branch's older-dated commits are merged back, landing below the
    # already-folded mainline block in git log's date order.
    _git(repo, "checkout", "-q", "feature")
    _commit_dated(repo, "F1 feature delta-marker", "2026-01-02")
    _commit_dated(repo, "F2 feature epsilon-marker", "2026-01-03")
    _git(repo, "checkout", "-q", default_branch)
    merge_env = {
        **os.environ,
        "GIT_AUTHOR_DATE": "2026-02-07T12:00:00",
        "GIT_COMMITTER_DATE": "2026-02-07T12:00:00",
    }
    subprocess.run(
        ["git", "-C", str(repo), "merge", "--no-ff", "-q", "feature", "-m", "M merge omega-marker"],
        check=True,
        env=merge_env,
    )

    folded = fold_git_log(pid, repo, root=store_root)

    # The merge commit and both deep feature commits fold — none lost to paging.
    assert folded == 3
    stored = "".join(log.read_text() for log in long_term_dir(pid, store_root).glob("*.md"))
    assert "delta-marker" in stored
    assert "epsilon-marker" in stored
    assert "omega-marker" in stored


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


def test_crash_mid_fold_folds_each_commit_once(
    store_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fold interrupted partway records each sha as it goes, so the next fold
    re-duplicates no already-folded commit — the crash window is one commit, not
    the whole batch (#41)."""

    ensure_store(store_root)
    repo = init_repo(tmp_path / "repo", commit=True)
    shas = [_commit(repo, f"Commit number {i}") for i in range(6)]
    pid = _project(store_root, repo)

    # Abort the fold after a few commits, standing in for a killed SessionEnd hook.
    real_append = append_entry
    appended = {"count": 0}

    def crashing_append(project_id: str, day: str, entry: str, root: Path | None = None) -> None:
        if appended["count"] >= 3:
            raise RuntimeError("simulated crash mid-fold")
        appended["count"] += 1
        real_append(project_id, day, entry, root)

    monkeypatch.setattr(gitreader, "append_entry", crashing_append)
    with pytest.raises(RuntimeError):
        fold_git_log(pid, repo, root=store_root)

    # The next SessionEnd re-runs the fold to completion.
    monkeypatch.setattr(gitreader, "append_entry", real_append)
    fold_git_log(pid, repo, root=store_root)

    # Every commit is folded exactly once — no duplicated daily-log entries.
    log_text = "".join(p.read_text() for p in long_term_dir(pid, store_root).glob("*.md"))
    for sha in shas:
        assert log_text.count(f"git:{sha}") == 1


def test_git_ledger_stays_bounded(
    store_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Folding more commits than the dedup window keeps only the most recent shas,
    so the git ledger stays bounded instead of growing one sha per commit (#41)."""

    ensure_store(store_root)
    repo = init_repo(tmp_path / "repo", commit=True)
    for i in range(30):
        _commit(repo, f"Commit number {i}")
    pid = _project(store_root, repo)

    # Shrink the window so a single fold overflows it deterministically.
    def small_ledger(path: Path) -> Ledger:
        return Ledger(path, capacity=20)

    monkeypatch.setattr(gitreader, "Ledger", small_ledger)
    fold_git_log(pid, repo, root=store_root)

    ledger_file = long_term_dir(pid, store_root) / gitreader.GIT_LEDGER_FILENAME
    assert len(ledger_file.read_text().split()) <= 20


def test_still_reachable_commit_not_refolded_after_rotation(
    store_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A linear history longer than the dedup window is still folded idempotently.

    The bounded ledger keeps only its most recent shas (#41), but the reader records
    them newest-last, so the window retains the tip commits — and under reachability
    exclusion (#42) a tip sha's ``^``-exclude reaches every ancestor. So even after
    the ledger has rotated far past its capacity, every reachable commit stays
    excluded and a re-fold adds nothing.
    """

    ensure_store(store_root)
    repo = init_repo(tmp_path / "repo", commit=True)
    pid = _project(store_root, repo)

    # A dedup window (8) far narrower than the history it must keep idempotent.
    def small_ledger(path: Path) -> Ledger:
        return Ledger(path, capacity=8)

    monkeypatch.setattr(gitreader, "Ledger", small_ledger)

    # Fold a first batch, then add more commits than the capacity and fold again —
    # the extra commits push the older shas out of the window, rotating the ledger.
    for i in range(8):
        _commit(repo, f"First batch {i}")
    fold_git_log(pid, repo, root=store_root)
    for i in range(12):
        _commit(repo, f"Second batch {i}")
    fold_git_log(pid, repo, root=store_root)

    # The ledger has rotated well past its capacity, yet a further fold sees every
    # reachable commit as already folded and adds nothing.
    ledger_file = long_term_dir(pid, store_root) / gitreader.GIT_LEDGER_FILENAME
    assert len(ledger_file.read_text().split()) <= 8
    assert fold_git_log(pid, repo, root=store_root) == 0


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
