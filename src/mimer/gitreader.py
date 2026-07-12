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

from mimer.failure_log import log_failure
from mimer.index import index_if_present
from mimer.longterm import append_entry, long_term_dir
from mimer.paths import store_root
from mimer.redaction import redact
from mimer.storeio import append_text, project_lock

GIT_LEDGER_FILENAME = ".git-ledger"

# How many commits to read from git per page while walking history.
_PAGE_SIZE = 100

# Upper bound on a first backfill. Folding runs synchronously at a session
# boundary (SessionEnd), so an enormous repo's whole history must not stall it;
# the most recent commits up to this bound are folded and the truncation is
# logged rather than dropped silently (issue #42). Steady-state runs are not
# bounded here — they stop once a whole page is already folded.
_FIRST_FOLD_LIMIT = 2000

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


def git_commits(cwd: Path, *, limit: int | None = _PAGE_SIZE, skip: int = 0) -> list[Commit]:
    """Return commits for the repository at ``cwd``, newest first, or [] outside a repo.

    ``limit`` caps how many commits are returned (``None`` reads to the end of
    history); ``skip`` offsets into history, so a caller can page through a large
    history one window at a time.
    """

    # Build the log command; a None limit omits -n so the whole history is read.
    args = ["git", "-C", str(cwd), "log"]
    if limit is not None:
        args.append(f"-n{limit}")
    if skip:
        args.append(f"--skip={skip}")
    args += ["--no-color", f"--format=%H{_UNIT}%aI{_UNIT}%s{_UNIT}%b{_RECORD}"]

    try:
        result = subprocess.run(args, check=True, capture_output=True, text=True, timeout=15)
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

    On first adoption — an empty ledger — the whole history is folded, paging
    through ``git log`` until it is exhausted or the :data:`_FIRST_FOLD_LIMIT`
    safety bound is reached (a truncation is logged, never silent). On later runs
    only the not-yet-folded commits are folded; paging stops once a whole page is
    already folded, so re-running adds nothing, while a commit a merge orders
    behind an already-folded one is still picked up (issue #42). Non-git projects
    fold nothing.
    """

    root = root or store_root()

    # Decide and apply under the lock so two boundaries cannot double-fold.
    folded_days: set[str] = set()
    with project_lock(project_id, root=root):
        seen = _folded_shas(project_id, root)
        commits, truncated = _commits_to_fold(cwd, seen, first_fold=not seen)
        for commit in commits:
            append_entry(project_id, commit.date, _render(commit), root)
            append_text(_ledger_path(project_id, root), commit.sha)
            folded_days.add(commit.date)

    # A truncated first backfill stays observable in the failure log (issue #42).
    if truncated:
        log_failure(
            f"git backfill for project {project_id} stopped at the "
            f"{_FIRST_FOLD_LIMIT}-commit safety bound; older history was left unfolded",
            root=root,
        )

    # Index the days that gained entries, when an index exists.
    for day in folded_days:
        index_if_present(project_id, day, root)
    return len(commits)


def _commits_to_fold(cwd: Path, seen: set[str], *, first_fold: bool) -> tuple[list[Commit], bool]:
    """Collect the not-yet-folded commits to fold, newest first.

    Pages through history folding every commit not already in the ledger. A first
    fold has an empty ledger and folds the whole history, capped at
    :data:`_FIRST_FOLD_LIMIT`; the returned flag reports whether that bound
    truncated the walk (older, unfolded history remained), which the caller turns
    into a logged notice. A steady-state run stops once a whole page holds nothing
    new — deliberately *not* at the first already-folded SHA: a merge can bring in
    commits whose commit date predates an already-folded one, so ``git log`` lists
    them after it, and stopping early would drop them silently and permanently
    (issue #42).
    """

    to_fold: list[Commit] = []
    skip = 0
    while True:
        # Read the next page; an empty page means history is exhausted.
        page = git_commits(cwd, limit=_PAGE_SIZE, skip=skip)
        if not page:
            return to_fold, False

        # Fold every not-yet-folded commit on the page; a first fold stops the
        # moment it reaches its safety bound.
        new_on_page = 0
        for commit in page:
            if first_fold and len(to_fold) >= _FIRST_FOLD_LIMIT:
                return to_fold, True
            if commit.sha in seen:
                continue
            to_fold.append(commit)
            new_on_page += 1

        # A steady-state page with nothing new means everything older is folded too.
        if not first_fold and not new_on_page:
            return to_fold, False

        skip += len(page)


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
