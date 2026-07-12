"""Project-identity resolution (ADR 0008): turn a working directory into a stable
project id, consulting every identity signal together and never binding to
existing memory silently.

Signals, in resolution order: an opt-in ``.mimer`` marker, the normalised git
remote(s), and the absolute path. A marker or path/remote conflict that would
attach a new directory to existing memory is surfaced as a confirmation request
rather than resolved silently.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from mimer.paths import store_root
from mimer.registry import Registry
from mimer.store import ensure_store
from mimer.storeio import project_lock
from mimer.vcs import git_remotes, git_toplevel

# The opt-in marker file at a project root carrying its project id.
MARKER_FILENAME = ".mimer"

# Reserved lock id serialising registry read-modify-write across sessions.
REGISTRY_LOCK = "__registry__"

# URL schemes stripped during remote normalisation.
_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://")


def normalise_remote(url: str) -> str:
    """Normalise a git remote URL to a canonical ``host/path`` key.

    Strips the scheme, credentials and user prefix, drops a trailing ``.git``,
    lowercases the host and unifies SSH scp-style and URL forms, so every
    spelling of one remote collapses to a single key (ADR 0008). The path case is
    preserved.
    """

    s = url.strip()
    if not s:
        return ""

    # Remove a URL scheme, or detect SSH scp-style "host:path" (a colon before
    # any slash, and no scheme).
    scheme = _SCHEME_RE.match(s)
    scp_form = False
    if scheme:
        s = s[scheme.end() :]
    elif ":" in s.split("/", 1)[0]:
        scp_form = True

    # Strip "user[:password]@" credentials ahead of the host.
    if "@" in s:
        s = s.rsplit("@", 1)[1]

    # Separate host from path: scp uses "host:path"; URLs use "host[:port]/path".
    if scp_form:
        host, _, path = s.partition(":")
    else:
        host, _, path = s.partition("/")
        host = host.split(":", 1)[0]

    host = host.lower()
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]

    return f"{host}/{path}".rstrip("/") if path else host


def _slug(text: str) -> str:
    """Reduce arbitrary text to a filesystem-safe project-id slug."""

    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", text.strip())
    slug = re.sub(r"-{2,}", "-", slug).strip("-.")
    return slug or "project"


def _path_id(path: str) -> str:
    """Derive a stable, readable id for a path-keyed (non-git) project."""

    digest = hashlib.sha256(path.encode("utf-8")).hexdigest()[:8]
    return f"{_slug(Path(path).name)}-{digest}"


class ResolutionStatus(Enum):
    """The outcome of resolving a directory to a project id."""

    CREATED = "created"
    RECOGNISED = "recognised"
    RECONCILED = "reconciled"
    NEEDS_CONFIRMATION = "needs_confirmation"


@dataclass(frozen=True)
class Resolution:
    """The result of resolution: a bound id, or a confirmation request.

    ``project_id`` is None only for :data:`ResolutionStatus.NEEDS_CONFIRMATION`,
    where ``candidate_id`` names the existing project a signal points at.
    """

    status: ResolutionStatus
    project_id: str | None
    candidate_id: str | None = None
    reason: str = ""


@dataclass(frozen=True)
class Signals:
    """The identity signals gathered from a working directory."""

    marker_id: str | None
    path: str
    remotes: list[str]
    preferred_remote: str | None


def gather_signals(cwd: Path) -> Signals:
    """Collect the marker, path and remote signals for ``cwd`` (ADR 0008).

    A marker scopes identity to its own directory (the monorepo case), so when a
    marker is present the path is the marker's directory and the repo's remotes
    are ignored; otherwise the path is the git top level (or the directory
    itself) and every remote is considered.
    """

    cwd = Path(cwd)

    # A non-empty marker declares an explicit id and scopes identity to its dir.
    marker_id = _read_marker(cwd)
    if marker_id is not None:
        return Signals(
            marker_id=marker_id, path=str(cwd.resolve()), remotes=[], preferred_remote=None
        )

    # Otherwise identity follows the repository: its top level and its remotes.
    toplevel = git_toplevel(cwd)
    path = toplevel if toplevel is not None else str(cwd.resolve())

    remotes_by_name = git_remotes(cwd)
    normalised = sorted({normalise_remote(url) for url in remotes_by_name.values() if url.strip()})
    preferred = _preferred_remote(remotes_by_name)
    return Signals(marker_id=None, path=path, remotes=normalised, preferred_remote=preferred)


def _read_marker(cwd: Path) -> str | None:
    """Return the slugged id declared by a ``.mimer`` marker, or None."""

    marker = cwd / MARKER_FILENAME
    if not marker.is_file():
        return None

    content = marker.read_text(encoding="utf-8").strip()
    return _slug(content) if content else None


def _preferred_remote(remotes_by_name: dict[str, str]) -> str | None:
    """Choose the preferred remote: ``origin`` if present, else first by name."""

    if not remotes_by_name:
        return None

    name = "origin" if "origin" in remotes_by_name else sorted(remotes_by_name)[0]
    return normalise_remote(remotes_by_name[name])


def resolve(cwd: Path, *, root: Path | None = None) -> Resolution:
    """Resolve ``cwd`` to a project id, binding safe cases and surfacing unsafe
    ones for confirmation.

    Safe bindings (a brand-new project, an already-known directory, a remote or
    path that unambiguously extends a known project) are persisted to the
    registry. A marker claiming existing memory from an unseen directory, or a
    path/remote pointing at different projects, returns
    :data:`ResolutionStatus.NEEDS_CONFIRMATION` and writes nothing.
    """

    root = root or store_root()
    ensure_store(root)

    # Gathering signals reads git and the filesystem, not the store, so it can
    # happen before the lock.
    signals = gather_signals(cwd)

    # The whole registry read-modify-write runs under a store-level lock, so two
    # concurrent sessions cannot lose each other's binding or race the atomic
    # write (ADR 0011).
    with project_lock(REGISTRY_LOCK, root=root):
        registry = Registry.load(root)
        if signals.marker_id is not None:
            return _resolve_marker(registry, signals)
        if signals.remotes:
            return _resolve_with_remote(registry, signals)
        return _resolve_path_only(registry, signals)


def _resolve_marker(registry: Registry, signals: Signals) -> Resolution:
    """Resolve when an explicit marker is present."""

    assert signals.marker_id is not None
    existing = registry.find_by_id(signals.marker_id)

    if existing is None:
        # Unrecognised marker → a fresh project with the declared id.
        registry.create(signals.marker_id, paths=[signals.path])
        registry.save()
        return Resolution(ResolutionStatus.CREATED, signals.marker_id)

    if signals.path in existing.paths:
        # The marker's directory is already linked here.
        return Resolution(ResolutionStatus.RECOGNISED, existing.id)

    # A marker claiming existing memory from an unseen directory is untrusted.
    return Resolution(
        ResolutionStatus.NEEDS_CONFIRMATION,
        None,
        candidate_id=existing.id,
        reason="marker maps to an existing project from a new directory",
    )


def _resolve_with_remote(registry: Registry, signals: Signals) -> Resolution:
    """Resolve when the repository has one or more remotes."""

    remote_ids = {
        record.id
        for record in (registry.find_by_remote(remote) for remote in signals.remotes)
        if record is not None
    }
    path_record = registry.find_by_path(signals.path)

    if remote_ids:
        if len(remote_ids) > 1:
            return Resolution(
                ResolutionStatus.NEEDS_CONFIRMATION,
                None,
                reason="remotes map to more than one project",
            )
        (matched_id,) = tuple(remote_ids)
        if path_record is not None and path_record.id != matched_id:
            return Resolution(
                ResolutionStatus.NEEDS_CONFIRMATION,
                None,
                candidate_id=matched_id,
                reason="path and remote map to different projects",
            )
        return _adopt(registry, matched_id, signals)

    if path_record is not None:
        # A known path acquiring a new remote → reconcile onto it, never a fresh id.
        return _adopt(registry, path_record.id, signals)

    # A brand-new remote project, keyed by its preferred remote.
    assert signals.preferred_remote is not None
    new_id = _slug(signals.preferred_remote)
    registry.create(new_id, remotes=signals.remotes, paths=[signals.path])
    registry.save()
    return Resolution(ResolutionStatus.CREATED, new_id)


def _resolve_path_only(registry: Registry, signals: Signals) -> Resolution:
    """Resolve a project with neither marker nor remote — keyed by path."""

    path_record = registry.find_by_path(signals.path)
    if path_record is not None:
        return Resolution(ResolutionStatus.RECOGNISED, path_record.id)

    new_id = _path_id(signals.path)
    registry.create(new_id, paths=[signals.path])
    registry.save()
    return Resolution(ResolutionStatus.CREATED, new_id)


def _adopt(registry: Registry, project_id: str, signals: Signals) -> Resolution:
    """Attach the current signals to an existing project, recording new aliases."""

    changed = registry.add_aliases(project_id, remotes=signals.remotes, paths=[signals.path])
    registry.save()
    status = ResolutionStatus.RECONCILED if changed else ResolutionStatus.RECOGNISED
    return Resolution(status, project_id)


def confirm_link(cwd: Path, candidate_id: str, *, root: Path | None = None) -> Resolution:
    """Bind ``cwd``'s signals to ``candidate_id`` after the user confirms it.

    This is the deliberate act that honours a marker or resolves a conflict that
    :func:`resolve` refused to bind silently. Confirming makes ``candidate_id`` the
    sole owner of this directory's signals: every *other* project that currently
    owns one of the signal remotes or the signal path is folded into the candidate
    via :meth:`Registry.merge` (ADR 0008 reconciliation, made lossless by #33). A
    bare additive alias would leave those records competing, so the next
    :func:`resolve` would surface the same NEEDS_CONFIRMATION forever — the dead
    end this fixes (#34).
    """

    root = root or store_root()
    ensure_store(root)
    signals = gather_signals(cwd)

    with project_lock(REGISTRY_LOCK, root=root):
        registry = Registry.load(root)
        if registry.find_by_id(candidate_id) is None:
            raise ValueError(f"unknown project id: {candidate_id}")

        # Fold each competing project into the candidate, then record the signals,
        # so the candidate alone owns this directory's remotes and path and
        # resolution stops asking.
        for conflicting_id in _conflicting_ids(registry, signals, candidate_id):
            registry.merge(conflicting_id, candidate_id)
        registry.add_aliases(candidate_id, remotes=signals.remotes, paths=[signals.path])
        registry.save()

    return Resolution(ResolutionStatus.RECOGNISED, candidate_id)


def _conflicting_ids(registry: Registry, signals: Signals, candidate_id: str) -> list[str]:
    """The ids of projects, other than the candidate, that currently own one of
    this directory's signals — the records that must fold into the candidate for
    resolution to stop returning NEEDS_CONFIRMATION (#34).

    Order-preserving and de-duplicated: two signals owned by the same competitor
    yield that competitor once.
    """

    owners: dict[str, None] = {}
    for remote in signals.remotes:
        record = registry.find_by_remote(remote)
        if record is not None and record.id != candidate_id:
            owners[record.id] = None

    path_record = registry.find_by_path(signals.path)
    if path_record is not None and path_record.id != candidate_id:
        owners[path_record.id] = None

    return list(owners)


def confirm_hint(candidate_id: str | None) -> str:
    """The one-line instruction that makes a refused identity resolvable (#34).

    A :data:`ResolutionStatus.NEEDS_CONFIRMATION` is a correct-by-design refusal,
    but a refusal with no "yes" is a dead end. This names the exact command that
    reaches :func:`confirm_link`, and the candidate project id to link to when
    resolution identified one; where it did not (ambiguous remotes mapping to more
    than one project), it names the command with a placeholder for the intended
    id.
    """

    if candidate_id is not None:
        return f"Run 'mimer-manage confirm {candidate_id}' to link this directory to that project."
    return (
        "Run 'mimer-manage confirm <project-id>' with the intended project id "
        "to link this directory."
    )
