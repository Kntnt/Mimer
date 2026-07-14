"""The project registry: the store-level record mapping each project id to its
known remotes and paths and per-project settings. It is the mechanism that
reconciles moved, renamed or cloned projects (ADR 0008).

The registry is a single JSON file at the store root, persisted through storeio's
atomic write primitive (ADR 0011's write-discipline map) so a crash never leaves a
half-written registry; the richer per-project lock discipline arrives in #3 and
layers on top.
"""

from __future__ import annotations

import json
import os
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass, field
from pathlib import Path

from mimer.paths import store_root
from mimer.store import DIR_MODE, ensure_store
from mimer.storeio import append_fold, named_lock, project_lock, write_atomic

# The registry file and the per-project memory directory both live under the
# store root.
REGISTRY_FILENAME = "registry.json"
PROJECTS_DIRNAME = "projects"


def registry_path(root: Path) -> Path:
    """Path to the registry file within ``root``."""

    return root / REGISTRY_FILENAME


def project_dir(project_id: str, root: Path) -> Path:
    """Path to a project's memory directory within ``root``."""

    return root / PROJECTS_DIRNAME / project_id


def registry_lock(*, root: Path | None = None) -> AbstractContextManager[None]:
    """Hold the store-wide lock guarding the registry read-modify-write.

    The registry (``registry.json``) belongs to no single project, so its lock is a
    store-wide named lock rather than a per-project one. This names that lock by the
    artefact its module owns and delegates to :func:`mimer.storeio.named_lock` under
    the name ``"registry"``; the resulting lock file is the same one earlier
    processes used, so old and new processes still contend on the same lock
    (ADR 0011).
    """

    return named_lock("registry", root=root)


@dataclass
class ProjectRecord:
    """One project's registry entry: its stable id and every alias that resolves
    to it, plus per-project settings."""

    id: str
    remotes: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)
    settings: dict[str, object] = field(default_factory=dict)


class Registry:
    """An in-memory view of the registry, loaded from and saved to one JSON file.

    Construct via :meth:`load`; mutate through the ``create``/``add_aliases``/
    ``merge`` methods; persist with :meth:`save`.
    """

    def __init__(self, root: Path, records: dict[str, ProjectRecord]) -> None:
        self._root = root
        self._records = records

    @classmethod
    def load(cls, root: Path | None = None) -> Registry:
        """Load the registry from ``root``; an absent file yields an empty one."""

        root = root or store_root()

        path = registry_path(root)
        if not path.exists():
            return cls(root, {})

        raw = json.loads(path.read_text(encoding="utf-8"))
        records = {
            entry["id"]: ProjectRecord(
                id=entry["id"],
                remotes=list(entry.get("remotes", [])),
                paths=list(entry.get("paths", [])),
                settings=dict(entry.get("settings", {})),
            )
            for entry in raw.get("projects", [])
        }
        return cls(root, records)

    def save(self) -> None:
        """Persist the registry atomically with owner-only permissions.

        Routes through :func:`mimer.storeio.write_atomic` — the store's single
        atomic, owner-only write primitive (ADR 0011's write-discipline map) — so
        the registry stays on the one storeio write path and inherits its
        temp-reap on a failed write, rather than repeating an inline
        temp-file-then-replace recipe here.
        """

        ensure_store(self._root)

        # Serialise every record and persist it through storeio, so a reader never
        # sees a partial registry and a failed write leaves no orphan temp behind.
        payload = {"projects": [asdict(record) for record in self._records.values()]}
        serialised = json.dumps(payload, indent=2, ensure_ascii=False)
        write_atomic(registry_path(self._root), serialised + "\n")

    def find_by_id(self, project_id: str) -> ProjectRecord | None:
        """Return the record with this id, or None."""

        return self._records.get(project_id)

    def find_by_remote(self, remote: str) -> ProjectRecord | None:
        """Return the record that lists this (normalised) remote, or None."""

        return next((r for r in self._records.values() if remote in r.remotes), None)

    def find_by_path(self, path: str) -> ProjectRecord | None:
        """Return the record that lists this path, or None."""

        return next((r for r in self._records.values() if path in r.paths), None)

    def project_ids(self) -> list[str]:
        """Return every registered project id."""

        return list(self._records)

    def is_widenable(self, project_id: str) -> bool:
        """Whether a project participates in widened recall (ADR 0013).

        Projects participate by default; only an explicit per-project setting
        excludes one. An unregistered project participates.
        """

        record = self._records.get(project_id)
        return not (record is not None and record.settings.get("exclude_from_widening") is True)

    def set_widening(self, project_id: str, *, participate: bool) -> None:
        """Set whether a project participates in widened recall."""

        self._records[project_id].settings["exclude_from_widening"] = not participate

    def capture_enabled(self, project_id: str) -> bool:
        """Whether automatic capture is enabled for a project (ADR 0013).

        Capture is on by default; only an explicit per-project setting turns it
        off. An unregistered project captures.
        """

        record = self._records.get(project_id)
        return not (record is not None and record.settings.get("capture") is False)

    def set_capture(self, project_id: str, *, enabled: bool) -> None:
        """Turn automatic capture on or off for a project."""

        self._records[project_id].settings["capture"] = enabled

    def distill_to_global_enabled(self, project_id: str) -> bool:
        """Whether a project's knowledge may be distilled with global scope
        (ADR 0013).

        Enabled by default; only an explicit per-project setting keeps a
        project's distillations project-scoped. An unregistered project is
        enabled.
        """

        record = self._records.get(project_id)
        return not (record is not None and record.settings.get("distill_to_global") is False)

    def set_distill_to_global(self, project_id: str, *, enabled: bool) -> None:
        """Set whether a project's knowledge may travel globally via distillation."""

        self._records[project_id].settings["distill_to_global"] = enabled

    def create(
        self,
        project_id: str,
        *,
        remotes: list[str] | None = None,
        paths: list[str] | None = None,
    ) -> ProjectRecord:
        """Register a new project. Raises if the id already exists."""

        if project_id in self._records:
            raise ValueError(f"project id already exists: {project_id}")

        record = ProjectRecord(id=project_id, remotes=list(remotes or []), paths=list(paths or []))
        self._records[project_id] = record
        return record

    def add_aliases(
        self,
        project_id: str,
        *,
        remotes: list[str] | None = None,
        paths: list[str] | None = None,
    ) -> bool:
        """Add any missing remote/path aliases to a project; return whether the
        record changed."""

        record = self._records[project_id]

        changed = False
        for remote in remotes or []:
            if remote and remote not in record.remotes:
                record.remotes.append(remote)
                changed = True
        for path in paths or []:
            if path and path not in record.paths:
                record.paths.append(path)
                changed = True
        return changed

    def merge(self, source_id: str, target_id: str) -> ProjectRecord:
        """Merge an orphaned project into its recognised identity.

        The source's aliases fold into the target, its per-project settings
        reconcile into the target, its memory directory's contents move under the
        target, and the source entry is removed. This is the link/merge
        reconciliation action of ADR 0008, made a live action by #34
        (``mimer-manage confirm``).

        Settings policy. The target's explicitly-set values win: a deliberate
        binding on the recognised identity is never overridden by a retired
        orphan's stale value. Where the target has not set a control, the
        source's value is adopted — so a capture the user paused on the orphan
        (#35) stays paused rather than silently re-enabling.
        """

        source = self._records[source_id]
        target = self._records[target_id]

        # Fold the orphan's aliases into the canonical record.
        self.add_aliases(target_id, remotes=source.remotes, paths=source.paths)

        # Reconcile per-project settings, target-wins: a control the target set
        # explicitly is kept, one it never set adopts the source's value so a
        # paused capture is not silently re-enabled (#35).
        target.settings = {**source.settings, **target.settings}

        # Move any on-disk memory from the orphan's directory into the target's.
        self._move_project_memory(source_id, target_id)

        del self._records[source_id]
        return target

    def _move_project_memory(self, source_id: str, target_id: str) -> None:
        """Merge the source project's on-disk memory into the target's, keeping
        every entry under nominal operation.

        The move is recursive and collision-aware (issue #33): subdirectories are
        merged in place rather than replaced — so a non-empty ``long-term/`` or
        ``transcripts/`` on both sides no longer makes ``os.replace`` raise
        ``ENOTEMPTY`` mid-loop — and a file present on both sides is combined by
        artefact type rather than silently overwritten. The source directory is
        drained and removed only after everything has moved.

        Concurrency (ADR 0011). The merge holds the target's per-project lock
        throughout. ``short-term.md`` is combined read-modify-write inside that
        lock, and its live writers (the memory skill and the boundary pass) take
        the same lock, so a concurrent update to it cannot be lost. Every
        append-only artefact — daily logs, the capture ledger, the distilled
        queue, transcripts — is folded with ``O_APPEND`` (see
        :func:`_concatenate_file`), matching its lockless producers, so a
        concurrent append is neither lost nor able to truncate the target, whether
        or not that producer holds any lock.

        Not attempted. The merge is not crash- or failure-atomic across artefacts.
        An unexpected error part-way leaves the already-folded artefacts in the
        target; and because a fold keeps the source file and appends its bytes to
        the target, a retry after a crash between folding an artefact and unlinking
        it re-appends — duplicates — it (harmless for ``short-term.md``, which
        dedups; a duplicate line elsewhere). The source directory is also drained
        and removed before the caller persists the registry, and only the target is
        locked: a crash between the drain and ``save`` leaves the registry still
        naming an emptied source, and a stray writer still resolving to the retired
        source id is not serialised against the drain. These residuals became live
        exposure once #34 made merge a user-invokable action (``mimer-manage
        confirm``); they are known and accepted for now, and remain the candidates
        to harden as the action's usage grows.
        """

        source_dir = project_dir(source_id, self._root)
        if not source_dir.exists():
            return

        # Run the whole merge under the target's lock so a concurrent writer to
        # the live target cannot lose an update (ADR 0011); the source is a
        # retired orphan, so only the target's lock is contended.
        with project_lock(target_id, root=self._root):
            _merge_directory(source_dir, project_dir(target_id, self._root), target_id)
            source_dir.rmdir()


def _merge_directory(source_dir: Path, target_dir: Path, target_id: str) -> None:
    """Recursively merge ``source_dir`` into ``target_dir``, emptying the source.

    A leaf absent on the target is moved outright; a leaf present on both sides is
    combined by :func:`_combine_files`; a subdirectory recurses. Each source
    subdirectory is removed once drained, as the walk unwinds.
    """

    # Create the target with owner-only access, re-tightening the mode even when it
    # pre-existed under a looser umask, so a merge never widens the store's 0700
    # directory invariant (ADR 0013) — mirroring both :func:`mimer.store.ensure_store`
    # for directories and the fold's re-chmod of combined files.
    target_dir.mkdir(mode=DIR_MODE, parents=True, exist_ok=True)
    target_dir.chmod(DIR_MODE)

    # Fold each source entry into the target, recursing into subdirectories and
    # combining colliding leaf files instead of clobbering them.
    for item in source_dir.iterdir():
        destination = target_dir / item.name
        if item.is_dir():
            _merge_directory(item, destination, target_id)
            item.rmdir()
        elif destination.exists():
            _combine_files(item, destination, target_id)
            item.unlink()
        else:
            os.replace(item, destination)


def _combine_files(source_file: Path, target_file: Path, target_id: str) -> None:
    """Combine a leaf file present on both sides of a merge, keeping every entry.

    ``short-term.md`` is a structured document, so its dated entries are merged
    section by section (duplicates dropped) under the target's id and rewritten
    atomically. Every other project artefact — daily logs, the capture ledger, the
    distilled queue, archived transcripts — is append-only, so the source's content
    is folded onto the end of the target's with ``O_APPEND`` rather than
    overwritten (see :func:`_concatenate_file`).
    """

    # Imported lazily: shortterm depends on this module for ``project_dir``, so a
    # top-level import would be circular.
    from mimer.shortterm import SHORT_TERM_FILENAME, merge_documents

    if target_file.name == SHORT_TERM_FILENAME:
        merged = merge_documents(
            target_file.read_text(encoding="utf-8"),
            source_file.read_text(encoding="utf-8"),
            target_id,
        )
        write_atomic(target_file, merged)
    else:
        _concatenate_file(source_file, target_file)


def _concatenate_file(source_file: Path, target_file: Path) -> None:
    """Fold the source file's records onto the end of the target's, losing none.

    Every append-only artefact this handles — daily logs, the capture ledger, the
    distilled queue, archived transcripts — is written by its live producer with
    lockless ``O_APPEND`` (:func:`mimer.storeio.append_text`), which ignores the
    project lock. Folding by read-modify-write would silently drop any
    record a producer appended between the read and the rewrite, so the fold uses
    ``O_APPEND`` too (:func:`mimer.storeio.append_fold`): the source's bytes land
    at the target's end-of-file, never truncating it and never racing a concurrent
    appender. A newline is inserted at the seam when the target does not already
    end with one, so the target's last record and the source's first never fuse
    into a single line.

    Collision semantics (deliberate). This concatenates unconditionally, so a
    same-named ``transcripts/<name>.jsonl`` on both sides — whose name encodes the
    session, i.e. the identical session archived under both project ids, hence
    byte-identical files — has its events written twice. No data is lost, but a
    downstream reader that replays or indexes the transcript would double-count the
    duplicated events. This became live exposure once #34 made merge a
    user-invokable action; it is known and accepted for now, and a
    keep-target-when-identical or dedup-by-line policy remains a candidate to weigh
    as usage grows, alongside the other residuals noted on
    :meth:`Registry._move_project_memory`.
    """

    # Read the target only to decide the seam; it is never written back, so a
    # record a producer appends after this read is preserved by the fold below.
    existing = target_file.read_text(encoding="utf-8")
    addition = source_file.read_text(encoding="utf-8")
    separator = "" if not existing or existing.endswith("\n") else "\n"

    append_fold(target_file, separator + addition)
