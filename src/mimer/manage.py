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

import argparse
from dataclasses import dataclass
from pathlib import Path

from mimer.bundle import (
    Concept,
    list_concepts,
    profile_concepts,
    promote_to_global,
    read_concept,
    retract_concept,
    visible_concepts,
)
from mimer.framing import frame, neutralise
from mimer.native_memory import disable_native_memory
from mimer.paths import LOG_FILENAME, store_root
from mimer.pause import clear_paused, is_paused, set_paused
from mimer.project import confirm_link, resolve
from mimer.redaction import redact
from mimer.registry import Registry, registry_lock
from mimer.storewalk import daily_log_days, disk_project_ids, known_project_ids
from mimer.vcs import git_toplevel

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
    last_activity: str | None
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
    with registry_lock(root=root):
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
    """The pinned profile Concepts, with their citations.

    Enumerates through :func:`mimer.bundle.profile_concepts` — the pinned subset of
    the Visible seam — so "what do you know about me?" shows exactly the pinned set
    injection shows, a forgotten pinned fact absent from both (issue #54).
    """

    return profile_concepts(root)


def recent_concepts(
    root: Path | None = None, *, project_id: str | None = None, limit: int = 10
) -> list[Concept]:
    """The recently learned Concepts visible to a project, newest first.

    Enumerates through the Visible seam (:func:`mimer.bundle.visible_concepts`), so
    "what did you learn recently?" hides a superseded, out-of-scope or forgotten
    Concept exactly as injection and recall do (issue #54).
    """

    visible = visible_concepts(root, project_id=project_id)
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
        # The most recent day any project's long-term log was written: the store's
        # last activity. Never a "session digest" — that intermediate block was
        # removed (ADR 0023, #63); health reports last activity, not a digest (#69).
        last_activity=max(days, default=None),
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


def build_parser() -> argparse.ArgumentParser:
    """Construct ``mimer-manage``'s argument parser, with one subparser per command.

    Exposed as its own seam, not built inline in :func:`main`, so the exact set of
    subcommands the CLI accepts is introspectable: the doc-truthfulness sweep asserts
    the README advertises only subcommands that really exist here, closing the hole
    that let a docs pointer to a non-existent subcommand ship green (integration
    finding, #68/#69).
    """

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
    subparsers.add_parser(
        "disable-native-memory", help="set autoMemoryEnabled: false for this project"
    )
    subparsers.add_parser("distill-now", help="distil this session's durable knowledge on demand")
    promote = subparsers.add_parser(
        "promote", help="promote a held Concept to global scope by slug"
    )
    promote.add_argument("slug")
    settings = subparsers.add_parser("settings", help="show or change per-project settings")
    settings.add_argument("name", nargs="?", choices=SETTING_NAMES, help="the setting to change")
    settings.add_argument("value", nargs="?", choices=("on", "off"), help="on or off")
    return parser


def main(argv: list[str] | None = None) -> int:
    """``mimer-manage`` entry point: inspect and correct permanent memory."""

    args = build_parser().parse_args(argv)

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
    elif args.command == "disable-native-memory":
        return _run_disable_native_memory()
    elif args.command == "distill-now":
        return _run_distill_now(root)
    elif args.command == "promote":
        return _run_promote(args.slug, root)
    else:
        return _run_settings(args.name, args.value, root)
    return 0


def _run_disable_native_memory(cwd: Path | None = None) -> int:
    """Set ``autoMemoryEnabled: false`` for this directory's project (ADR 0025).

    This is the command the SessionStart warning and the README point the user at:
    it writes the project-scoped switch at the project root the warning reads — the
    git top level, or the directory itself outside a repo — so a disable run from a
    subdirectory silences next session's warning rather than writing a stray
    subdirectory settings file the warning never consults. A ``.claude/settings.json``
    that cannot be read or parsed — malformed or non-object content (``ValueError``),
    or an unreadable file such as a directory standing in its place or a permission
    quirk (``OSError``) — is refused, not clobbered: ``disable_native_memory`` reads
    before it writes and raises, leaving the file intact, and this reports a clean
    one-line rejection with a non-zero exit rather than leaking a traceback for the
    user's own config (mirrors ``retract`` and ``confirm``). The ``OSError`` case is
    caught here because the SessionStart warning's read path already survives that same
    stray state (``is_native_memory_enabled``, #68); the command the warning points to
    must not then die on it (integration finding, #68/#69).
    """

    # Resolve the project root the switch belongs to — the repository top level the
    # SessionStart warning keys on, not the raw session cwd — so the write lands
    # where Claude Code and the warning both read .claude/settings.json.
    cwd = cwd or Path.cwd()
    toplevel = git_toplevel(cwd)
    project_root = Path(toplevel) if toplevel is not None else cwd

    # Refuse rather than destroy a settings.json we cannot use: disable_native_memory
    # reads before it writes, so unparseable or non-object content (ValueError) and an
    # unreadable file — a directory in its place, a permission quirk (OSError) — both
    # raise before any write and leave the file byte-for-byte intact. Surface either as
    # a one-line rejection, never a traceback; OSError matches the SessionStart read
    # path that already survives the same stray state (#68).
    try:
        disable_native_memory(project_root)
    except (ValueError, OSError) as exc:
        print(f"Mimer: could not disable native auto memory — {exc}")
        return 1

    print(
        f'Mimer: native auto memory disabled for "{project_root}" — '
        "autoMemoryEnabled is now false; the session-start warning stops here."
    )
    return 0


# The one-line outcome per boundary-pass status for the on-demand verb. The
# durable "remember this" promotion always runs first, model-independent (ADR 0023),
# so every non-error line says durable knowledge was distilled even when the model
# call itself found nothing new or deferred; the guard states name their own reason.
_DISTILL_NOW_OUTCOMES = {
    "completed": (
        "Mimer: distilled this session's durable knowledge on demand — short-term "
        "memory refreshed and durable facts promoted."
    ),
    "deferred": (
        "Mimer: distilled this session's durable entries on demand; the model pass "
        "deferred (headless Claude unavailable)."
    ),
    "nothing": (
        "Mimer: distilled this session's durable entries on demand; no additional "
        "raw-record facts to distil."
    ),
    "paused": "Mimer: capture is paused store-wide — nothing was distilled.",
    "capture-disabled": "Mimer: capture is off for this project — nothing was distilled.",
    "skipped-identity": (
        "Mimer: this directory's project identity needs confirmation — nothing was distilled."
    ),
    "failed": "Mimer: the on-demand distillation failed; see the failure log.",
}


def _run_distill_now(root: Path, cwd: Path | None = None) -> int:
    """Run the session-boundary distillation on demand (ADRs 0023, 0027).

    The manual counterpart to the automatic session-end pass: it publishes this
    session's durable knowledge to permanent memory immediately — so a long or
    parallel session need not wait for the boundary — and, because the user is
    present, resolves any sensitive-scope consent in the moment. It runs the pass
    with ``scope="global"`` (honouring the project's distill-to-global switch) and
    ``attended=True``, so a sensitive fact the leakage guard holds at project scope
    is surfaced here for an immediate promote-or-hold decision rather than queued for
    a next session start that may never come. The imported-here boundary entry point
    keeps the heavier index/model dependency graph off every other manage command.
    """

    from mimer.boundary import run_boundary_pass

    # Run the same pass the session boundary runs, but attended and global-bound, so
    # durable knowledge is published now and any held sensitive fact is returned for
    # in-the-moment resolution rather than deferred (ADR 0027).
    cwd = cwd or Path.cwd()
    result = run_boundary_pass({"cwd": str(cwd)}, root=root, scope="global", attended=True)
    print(_DISTILL_NOW_OUTCOMES.get(result.status, _DISTILL_NOW_OUTCOMES["failed"]))

    # Surface the held sensitive facts as the in-the-moment consent ask: you are
    # present, so decide now. The Concept titles are untrusted memory, so they are
    # neutralised and framed as inert data (ADR 0014); each slug is a path-safe
    # identifier and names the promote command that carries out a "yes".
    if result.held:
        concepts = [read_concept(slug, root) for slug in result.held]
        print(
            f"Mimer: {len(concepts)} sensitive fact(s) held at project scope, awaiting "
            "your consent to go global. You are present — decide now: run "
            '"mimer-manage promote <slug>" to publish one, or leave it project-scoped.'
        )
        listing = "\n".join(f"[{concept.slug}] {concept.title}" for concept in concepts)
        print(frame(neutralise(listing)))

    return 0


def _run_promote(slug: str, root: Path) -> int:
    """Promote a held Concept to global scope: the consent "yes" (ADR 0027).

    An unknown slug is rejected deep in ``read_concept`` (``OSError``) and a
    traversal-shaped one in ``safe_identifier`` (``ValueError``); both become a
    one-line rejection with a non-zero exit rather than a leaked traceback for user
    input, mirroring ``retract`` and ``confirm`` (#25).
    """

    try:
        concept = promote_to_global(slug, root)
    except (ValueError, OSError) as exc:
        print(f"Mimer: {exc}")
        return 1

    print(f'Mimer: promoted "{concept.title}" to global scope — it now reaches other projects.')
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
        f"Last activity: {report.last_activity or 'none'}; "
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
