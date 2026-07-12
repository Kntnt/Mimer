"""The project registry: the store-level record mapping each project id to its
known remotes and paths, per-project settings and import state. It is the
mechanism that reconciles moved, renamed or cloned projects (ADR 0008).

The registry is a single JSON file at the store root. Writes are atomic
(write-temp-then-replace) so a crash never leaves a half-written registry; the
richer per-project lock discipline arrives in #3 and layers on top.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from mimer.paths import store_root
from mimer.store import FILE_MODE, ensure_store

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


@dataclass
class ProjectRecord:
    """One project's registry entry: its stable id and every alias that resolves
    to it, plus per-project settings and import state for later stages."""

    id: str
    remotes: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)
    settings: dict[str, object] = field(default_factory=dict)
    import_state: dict[str, object] = field(default_factory=dict)


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
                import_state=dict(entry.get("import_state", {})),
            )
            for entry in raw.get("projects", [])
        }
        return cls(root, records)

    def save(self) -> None:
        """Persist the registry atomically with owner-only permissions."""

        ensure_store(self._root)

        payload = {"projects": [asdict(record) for record in self._records.values()]}
        serialised = json.dumps(payload, indent=2, ensure_ascii=False)

        # Write to a uniquely-named temp file then atomically replace, so a
        # reader never sees a partial registry and two concurrent writers never
        # collide on a shared temp path.
        target = registry_path(self._root)
        handle, tmp_name = tempfile.mkstemp(dir=self._root, prefix="registry.", suffix=".tmp")
        with os.fdopen(handle, "w", encoding="utf-8") as tmp_file:
            tmp_file.write(serialised + "\n")
        os.chmod(tmp_name, FILE_MODE)
        os.replace(tmp_name, target)

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

    def import_state(self, project_id: str) -> dict[str, object]:
        """Return a project's bootstrap import state (empty if none)."""

        record = self._records.get(project_id)
        return dict(record.import_state) if record is not None else {}

    def set_import_state(self, project_id: str, state: dict[str, object]) -> None:
        """Replace a project's bootstrap import state."""

        self._records[project_id].import_state = dict(state)

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

        The source's aliases fold into the target, its memory directory's
        contents move under the target, and the source entry is removed. This is
        the link/merge reconciliation action of ADR 0008.
        """

        source = self._records[source_id]
        target = self._records[target_id]

        # Fold the orphan's aliases into the canonical record.
        self.add_aliases(target_id, remotes=source.remotes, paths=source.paths)

        # Move any on-disk memory from the orphan's directory into the target's.
        self._move_project_memory(source_id, target_id)

        del self._records[source_id]
        return target

    def _move_project_memory(self, source_id: str, target_id: str) -> None:
        """Merge the source project's on-disk memory into the target's, losslessly.

        The move is recursive and collision-aware (issue #33): subdirectories are
        merged in place rather than replaced — so a non-empty ``long-term/`` or
        ``transcripts/`` on both sides no longer makes ``os.replace`` raise
        ``ENOTEMPTY`` mid-loop — and a file present on both sides is combined by
        artefact type rather than silently overwritten. The source directory is
        drained and removed only after everything has moved, so a merge is never
        left half-applied.
        """

        source_dir = project_dir(source_id, self._root)
        if not source_dir.exists():
            return

        _merge_directory(source_dir, project_dir(target_id, self._root), target_id)
        source_dir.rmdir()


def _merge_directory(source_dir: Path, target_dir: Path, target_id: str) -> None:
    """Recursively merge ``source_dir`` into ``target_dir``, emptying the source.

    A leaf absent on the target is moved outright; a leaf present on both sides is
    combined by :func:`_combine_files`; a subdirectory recurses. Each source
    subdirectory is removed once drained, as the walk unwinds.
    """

    target_dir.mkdir(parents=True, exist_ok=True)

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
    section by section (duplicates dropped) under the target's id. Every other
    project artefact — daily logs, the capture/digest/git ledgers, the distilled
    queue, archived transcripts — is append-only, so the source's content is
    concatenated onto the target's.
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
        target_file.write_text(merged, encoding="utf-8")
        target_file.chmod(FILE_MODE)
    else:
        _concatenate_file(source_file, target_file)


def _concatenate_file(source_file: Path, target_file: Path) -> None:
    """Append the source file's content onto the target's, preserving every line.

    A newline is inserted at the seam when the target does not already end with
    one, so the target's last record and the source's first never fuse into a
    single line.
    """

    existing = target_file.read_text(encoding="utf-8")
    addition = source_file.read_text(encoding="utf-8")

    separator = "" if not existing or existing.endswith("\n") else "\n"
    target_file.write_text(existing + separator + addition, encoding="utf-8")
    target_file.chmod(FILE_MODE)
