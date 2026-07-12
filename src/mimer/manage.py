"""The management surface (Stage 5c): see, question and correct what Mimer knows.

Exposes profile enumeration ("what do you know about me?"), recent distillations
("what did you learn recently?"), store health (sizes, counts, last activity,
recent failures) and retraction of a Concept. Recall over permanent memory with
scope enforcement lives in the index; this module is the inspection and
correction layer the memory skill drives.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mimer.bundle import Concept, list_concepts, profile_concepts, retract_concept
from mimer.longterm import LONG_TERM_DIRNAME
from mimer.paths import LOG_FILENAME, store_root
from mimer.redaction import redact
from mimer.registry import PROJECTS_DIRNAME, Registry

_RECENT_FAILURES = 5


@dataclass(frozen=True)
class HealthReport:
    """A snapshot of the store's size, contents and recent trouble."""

    concept_count: int
    project_count: int
    long_term_days: int
    store_bytes: int
    last_digest: str | None
    last_distillation: str | None
    recent_failures: list[str]


def profile(root: Path | None = None) -> list[Concept]:
    """The pinned profile Concepts, with their citations."""

    return profile_concepts(root)


def recent_concepts(
    root: Path | None = None, *, project_id: str | None = None, limit: int = 10
) -> list[Concept]:
    """Active Concepts visible to a project, newest first."""

    visible = [
        concept
        for concept in list_concepts(root)
        if concept.status == "active"
        and (project_id is None or concept.scope == "global" or concept.origin == project_id)
    ]
    visible.sort(key=lambda concept: concept.timestamp, reverse=True)
    return visible[:limit]


def store_health(root: Path | None = None) -> HealthReport:
    """Report the store's sizes, counts, last activity and recent failures."""

    root = root or store_root()
    concepts = list_concepts(root)

    projects_root = root / PROJECTS_DIRNAME
    project_dirs = (
        [d for d in projects_root.iterdir() if d.is_dir()] if projects_root.exists() else []
    )
    long_term_days = sum(
        len(list((directory / LONG_TERM_DIRNAME).glob("*.md")))
        for directory in project_dirs
        if (directory / LONG_TERM_DIRNAME).is_dir()
    )

    return HealthReport(
        concept_count=len(concepts),
        project_count=len(Registry.load(root).project_ids()) or len(project_dirs),
        long_term_days=long_term_days,
        store_bytes=_store_bytes(root),
        last_digest=_latest_daily_log(project_dirs),
        last_distillation=max((c.timestamp for c in concepts), default=None),
        recent_failures=_recent_failures(root),
    )


def _store_bytes(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def _latest_daily_log(project_dirs: list[Path]) -> str | None:
    days = [
        log.stem
        for directory in project_dirs
        for log in (directory / LONG_TERM_DIRNAME).glob("*.md")
        if (directory / LONG_TERM_DIRNAME).is_dir()
    ]
    return max(days, default=None)


def _recent_failures(root: Path) -> list[str]:
    # Redact each line on read: the log is user-writable and may hold legacy lines
    # written before write-time redaction existed, so `mimer-manage health` must not
    # echo a secret it happens to find there (issue #24).
    log = root / LOG_FILENAME
    if not log.exists():
        return []
    lines = [line for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [redact(line) for line in lines[-_RECENT_FAILURES:]]


def main(argv: list[str] | None = None) -> int:
    """``mimer-manage`` entry point: inspect and correct permanent memory."""

    import argparse

    parser = argparse.ArgumentParser(
        prog="mimer-manage", description="Inspect and correct Mimer's permanent memory."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("profile", help="enumerate the pinned profile")
    subparsers.add_parser("recent", help="list recently learned Concepts")
    subparsers.add_parser("health", help="report store health")
    retract = subparsers.add_parser("retract", help="retract a Concept by slug")
    retract.add_argument("slug")
    args = parser.parse_args(argv)

    root = store_root()
    if args.command == "profile":
        _print_concepts("Profile", profile(root))
    elif args.command == "recent":
        _print_concepts("Recently learned", recent_concepts(root))
    elif args.command == "health":
        _print_health(store_health(root))
    else:
        # A traversal-shaped slug is refused by safe_identifier deep inside
        # retract; turn that ValueError into a clear one-line rejection with a
        # non-zero exit rather than leaking a stack trace for user input (#25).
        try:
            concept = retract_concept(args.slug, root)
        except ValueError as exc:
            print(f"Mimer: {exc}")
            return 1
        print(f'Mimer: retracted "{concept.title}" — it will no longer surface.')
    return 0


def _print_concepts(heading: str, concepts: list[Concept]) -> None:
    if not concepts:
        print(f"Mimer: {heading.lower()} — nothing yet.")
        return
    print(f"Mimer: {heading}:")
    for concept in concepts:
        cites = f" [cited: {concept.citations[0].excerpt}]" if concept.citations else ""
        print(f"- {concept.title}: {concept.body}{cites}")


def _print_health(report: HealthReport) -> None:
    print(
        f"Mimer store: {report.concept_count} concept(s), {report.project_count} project(s), "
        f"{report.long_term_days} daily log(s), {report.store_bytes} bytes. "
        f"Last digest: {report.last_digest or 'none'}; "
        f"last distillation: {report.last_distillation or 'none'}."
    )
    if report.recent_failures:
        print("Recent failures:")
        for failure in report.recent_failures:
            print(f"- {failure}")
