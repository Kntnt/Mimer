"""Git as a capture source (Stage 6; ADR 0003).

Git is a *source*, never the store: commit messages fold into long-term memory
tagged with `git:<sha>` provenance and a quoted excerpt, behind the redaction
pass, idempotently. Because history rewrites happen (the very reason git is not
the store), the quoted excerpt keeps a citation checkable even after its SHA no
longer resolves. Non-git projects are skipped cleanly.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from mimer.index import index_if_present
from mimer.longterm import append_entry, long_term_dir
from mimer.paths import store_root
from mimer.redaction import redact
from mimer.storeio import append_text, project_lock

GIT_LEDGER_FILENAME = ".git-ledger"

# How many recent commits to consider each run.
_COMMIT_LIMIT = 100

# ASCII unit/record separators keep multi-line commit bodies unambiguous.
_UNIT = "\x1f"
_RECORD = "\x1e"


@dataclass(frozen=True)
class Commit:
    """A commit as a capture source."""

    sha: str
    subject: str
    body: str
    date: str


def git_commits(cwd: Path, *, limit: int = _COMMIT_LIMIT) -> list[Commit]:
    """Return recent commits for the repository at ``cwd``, or [] outside a repo."""

    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(cwd),
                "log",
                f"-n{limit}",
                "--no-color",
                f"--format=%H{_UNIT}%aI{_UNIT}%s{_UNIT}%b{_RECORD}",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return []

    commits = []
    for record in result.stdout.split(_RECORD):
        fields = record.strip("\n").split(_UNIT)
        if len(fields) < 4 or not fields[0]:
            continue
        sha, iso_date, subject, body = fields[0], fields[1], fields[2], fields[3]
        commits.append(Commit(sha, subject.strip(), body.strip(), iso_date[:10]))
    return commits


def fold_git_log(project_id: str, cwd: Path, root: Path | None = None) -> int:
    """Fold new commit messages into long-term memory; return the count folded.

    Idempotent: a commit already folded (recorded in the git ledger) is skipped,
    so re-running adds nothing.
    """

    root = root or store_root()
    commits = git_commits(cwd)
    if not commits:
        return 0

    folded = 0
    folded_days: set[str] = set()
    with project_lock(project_id, root=root):
        seen = _folded_shas(project_id, root)
        for commit in commits:
            if commit.sha in seen:
                continue
            append_entry(project_id, commit.date, _render(commit), root)
            append_text(_ledger_path(project_id, root), commit.sha)
            seen.add(commit.sha)
            folded += 1
            folded_days.add(commit.date)

    # Index the days that gained entries, when an index exists.
    for day in folded_days:
        index_if_present(project_id, day, root)
    return folded


def _render(commit: Commit) -> str:
    """Render a redacted daily-log entry carrying the commit's provenance."""

    subject = redact(commit.subject).strip()
    body = redact(commit.body).strip()
    message = f"{subject}\n\n{body}".strip() if body else subject
    return f"### git:{commit.sha} — {subject}\n{message}\n"


def _ledger_path(project_id: str, root: Path) -> Path:
    return long_term_dir(project_id, root) / GIT_LEDGER_FILENAME


def _folded_shas(project_id: str, root: Path) -> set[str]:
    path = _ledger_path(project_id, root)
    return set(path.read_text(encoding="utf-8").split()) if path.exists() else set()
