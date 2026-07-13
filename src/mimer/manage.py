"""The management surface (Stage 5c): see, question, correct and control what
Mimer knows.

Exposes profile enumeration ("what do you know about me?"), recent distillations
("what did you learn recently?"), store health (sizes, counts, last activity,
recent failures), retraction of a Concept, the session-level capture pause, and
the per-project settings ADR 0013 describes. Recall over permanent memory with
scope enforcement lives in the index; this module is the inspection, correction
and control layer the memory skill drives.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mimer.bundle import Concept, list_concepts, profile_concepts, retract_concept
from mimer.framing import frame, neutralise
from mimer.paths import LOG_FILENAME, store_root
from mimer.pause import clear_paused, is_paused, set_paused
from mimer.project import REGISTRY_LOCK, confirm_link, resolve
from mimer.redaction import redact
from mimer.registry import Registry
from mimer.storeio import project_lock
from mimer.storewalk import daily_log_days, disk_project_ids, known_project_ids

_RECENT_FAILURES = 5

# The user-facing per-project settings, in display order (ADR 0013).
SETTING_NAMES = ("capture", "distill-to-global", "widening")


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
    paused: bool
    capture_disabled_projects: list[str]


@dataclass(frozen=True)
class ProjectSettings:
    """A project's per-project controls (ADR 0013), each a plain on/off switch."""

    project_id: str
    capture: bool
    distill_to_global: bool
    widening: bool


def project_settings(
    cwd: Path | None = None, *, root: Path | None = None
) -> ProjectSettings | None:
    """Read the current project's per-project settings, or None when its identity
    needs confirmation."""

    root = root or store_root()

    resolution = resolve(cwd or Path.cwd(), root=root)
    if resolution.project_id is None:
        return None
    return _read_settings(Registry.load(root), resolution.project_id)


def set_project_setting(
    name: str, enabled: bool, *, cwd: Path | None = None, root: Path | None = None
) -> ProjectSettings | None:
    """Set one per-project setting, returning the project's settings afterwards.

    Returns None when the project's identity needs confirmation. The registry
    read-modify-write runs under the store-level registry lock, so a concurrent
    session cannot lose the change (ADR 0011).
    """

    root = root or store_root()

    resolution = resolve(cwd or Path.cwd(), root=root)
    project_id = resolution.project_id
    if project_id is None:
        return None

    # Apply the change under the registry lock, then read the result back. The
    # record is re-fetched inside the lock because a concurrent merge (ADR 0008)
    # could have folded this project away between resolve() and here; when it has,
    # there is nothing to set, so report the same "needs confirmation" signal
    # rather than raising a KeyError from the setters.
    with project_lock(REGISTRY_LOCK, root=root):
        registry = Registry.load(root)
        if registry.find_by_id(project_id) is None:
            return None
        _apply_setting(registry, project_id, name, enabled)
        registry.save()
        return _read_settings(registry, project_id)


def _apply_setting(registry: Registry, project_id: str, name: str, enabled: bool) -> None:
    """Route a user-facing setting name to its registry mutator."""

    if name == "capture":
        registry.set_capture(project_id, enabled=enabled)
    elif name == "distill-to-global":
        registry.set_distill_to_global(project_id, enabled=enabled)
    elif name == "widening":
        registry.set_widening(project_id, participate=enabled)
    else:
        raise ValueError(f"unknown setting: {name}")


def _read_settings(registry: Registry, project_id: str) -> ProjectSettings:
    """Assemble a project's settings from the registry's current view."""

    return ProjectSettings(
        project_id=project_id,
        capture=registry.capture_enabled(project_id),
        distill_to_global=registry.distill_to_global_enabled(project_id),
        widening=registry.is_widenable(project_id),
    )


def confirm_identity(
    candidate_id: str, *, cwd: Path | None = None, root: Path | None = None
) -> str:
    """Bind the current directory to ``candidate_id`` after the user confirms it.

    This is the reachable "yes" for a :data:`ResolutionStatus.NEEDS_CONFIRMATION`:
    it wraps :func:`mimer.project.confirm_link` so the identity a hook refused to
    bind silently can be settled from the management surface, after which
    injection and capture proceed (#34).

    Returns:
        The bound project id.

    Raises:
        ValueError: When no registered project carries ``candidate_id``.
    """

    root = root or store_root()

    resolution = confirm_link(cwd or Path.cwd(), candidate_id, root=root)
    assert resolution.project_id is not None
    return resolution.project_id


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
    registry = Registry.load(root)

    # Every day of long-term memory across the store, enumerated once by the store
    # walk so the day count and the last-activity timestamp read the same set.
    days = [
        day for project_id in disk_project_ids(root) for day in daily_log_days(project_id, root)
    ]

    # Enumerate every project whose capture is switched off; a per-project
    # capture-off is a standing, indefinite suppression that must be auditable
    # here rather than discoverable only from inside that exact project (#35).
    capture_disabled = [pid for pid in registry.project_ids() if not registry.capture_enabled(pid)]

    return HealthReport(
        concept_count=len(concepts),
        # The registry ∪ disk union, so a disk-only orphan is counted (issue #48).
        project_count=len(known_project_ids(root)),
        long_term_days=len(days),
        store_bytes=_store_bytes(root),
        last_digest=max(days, default=None),
        last_distillation=max((c.timestamp for c in concepts), default=None),
        recent_failures=_recent_failures(root),
        paused=is_paused(root),
        capture_disabled_projects=capture_disabled,
    )


def _store_bytes(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


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
        prog="mimer-manage", description="Inspect, correct and control Mimer's memory."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("profile", help="enumerate the pinned profile")
    subparsers.add_parser("recent", help="list recently learned Concepts")
    subparsers.add_parser("health", help="report store health")
    retract = subparsers.add_parser("retract", help="retract a Concept by slug")
    retract.add_argument("slug")
    confirm = subparsers.add_parser(
        "confirm", help="confirm this directory's project identity by candidate id"
    )
    confirm.add_argument("candidate_id")
    subparsers.add_parser("pause", help="pause capture for this session")
    subparsers.add_parser("resume", help="resume capture")
    settings = subparsers.add_parser("settings", help="show or change per-project settings")
    settings.add_argument("name", nargs="?", choices=SETTING_NAMES, help="the setting to change")
    settings.add_argument("value", nargs="?", choices=("on", "off"), help="on or off")
    args = parser.parse_args(argv)

    root = store_root()
    if args.command == "profile":
        _print_concepts("Profile", profile(root))
    elif args.command == "recent":
        _print_concepts("Recently learned", recent_concepts(root))
    elif args.command == "health":
        _print_health(store_health(root))
    elif args.command == "retract":
        # A traversal-shaped slug is refused by safe_identifier deep inside
        # retract; turn that ValueError into a clear one-line rejection with a
        # non-zero exit rather than leaking a stack trace for user input (#25).
        try:
            concept = retract_concept(args.slug, root)
        except ValueError as exc:
            print(f"Mimer: {exc}")
            return 1
        print(f'Mimer: retracted "{concept.title}" — it will no longer surface.')
    elif args.command == "confirm":
        # An unknown candidate id is rejected deep in confirm_link; turn that
        # ValueError into a clean one-line rejection with a non-zero exit rather
        # than leaking a stack trace for user input (#34).
        try:
            project_id = confirm_identity(args.candidate_id, root=root)
        except ValueError as exc:
            print(f"Mimer: {exc}")
            return 1
        print(
            f'Mimer: linked this directory to "{project_id}" — '
            "memory will now load and record here."
        )
    elif args.command == "pause":
        set_paused(root)
        print("Mimer: capture paused — nothing is recorded, store-wide, until you resume.")
    elif args.command == "resume":
        clear_paused(root)
        print("Mimer: capture resumed.")
    else:
        return _run_settings(args.name, args.value, root)
    return 0


def _run_settings(name: str | None, value: str | None, root: Path) -> int:
    """Show the current project's settings, or change one and echo the result."""

    # No name means "show": print every setting for the current project.
    if name is None:
        settings = project_settings(root=root)
        if settings is None:
            print("Mimer: the project identity needs confirmation before settings can be shown.")
            return 0
        _print_settings(settings)
        return 0

    # A named setting requires an explicit on/off value.
    if value is None:
        print(f"Mimer: say '{name} on' or '{name} off'.")
        return 2

    settings = set_project_setting(name, value == "on", root=root)
    if settings is None:
        print("Mimer: the project identity needs confirmation before settings can be changed.")
        return 0
    print(f'Mimer: {name} set to {value} for "{settings.project_id}".')
    return 0


def _print_settings(settings: ProjectSettings) -> None:
    """Print a project's per-project settings in one line."""

    def onoff(enabled: bool) -> str:
        return "on" if enabled else "off"

    print(
        f'Mimer: settings for "{settings.project_id}" — '
        f"capture {onoff(settings.capture)}, "
        f"distill-to-global {onoff(settings.distill_to_global)}, "
        f"widening {onoff(settings.widening)}."
    )


def _print_concepts(heading: str, concepts: list[Concept]) -> None:
    if not concepts:
        print(f"Mimer: {heading.lower()} — nothing yet.")
        return

    # Mimer's heading is its trusted voice and stays outside the frame; the
    # concept bodies and their cited excerpts are recalled from untrusted
    # memory, so they are neutralised as leaf values and wrapped in the data
    # frame (ADR 0014) — a directive that reached a Concept is echoed back here
    # as inert, fenced data, and any heading it carries is stripped rather than
    # left to reopen the context as a command.
    print(f"Mimer: {heading}:")
    lines = []
    for concept in concepts:
        cites = f" [cited: {concept.citations[0].excerpt}]" if concept.citations else ""
        lines.append(f"- {concept.title}: {concept.body}{cites}")
    print(frame(neutralise("\n".join(lines))))


def _print_health(report: HealthReport) -> None:
    print(
        f"Mimer store: {report.concept_count} concept(s), {report.project_count} project(s), "
        f"{report.long_term_days} daily log(s), {report.store_bytes} bytes. "
        f"Last digest: {report.last_digest or 'none'}; "
        f"last distillation: {report.last_distillation or 'none'}."
    )

    # Surface a standing pause loudly, so a forgotten or crash-stranded one is
    # never a silent, indefinite capture blackout (#35).
    if report.paused:
        print("Capture is PAUSED store-wide — nothing is being recorded; run 'resume' to lift it.")

    # Enumerate any project whose capture is switched off — a standing per-project
    # suppression that, like a pause, must be auditable rather than silent (#35).
    if report.capture_disabled_projects:
        joined = ", ".join(report.capture_disabled_projects)
        print(
            f"Capture is OFF for {len(report.capture_disabled_projects)} project(s): {joined} "
            "— nothing is recorded there until re-enabled with 'settings capture on'."
        )

    if report.recent_failures:
        print("Recent failures:")
        for failure in report.recent_failures:
            print(f"- {failure}")
