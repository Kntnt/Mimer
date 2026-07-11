"""Unit tests for the project registry: the store-level record mapping project
ids to their known remotes and paths, plus the merge that repairs an orphaned
project (ADR 0008).
"""

from __future__ import annotations

import json
import stat
from pathlib import Path

from mimer.registry import Registry, project_dir, registry_path
from mimer.store import ensure_store


def test_round_trips_records(tmp_path: Path) -> None:
    """Records survive a save/load cycle unchanged."""

    ensure_store(tmp_path)
    reg = Registry.load(tmp_path)
    reg.create("proj-a", remotes=["github.com/x/a"], paths=["/work/a"])
    reg.save()

    reloaded = Registry.load(tmp_path)
    record = reloaded.find_by_id("proj-a")
    assert record is not None
    assert record.remotes == ["github.com/x/a"]
    assert record.paths == ["/work/a"]


def test_lookup_by_remote_and_path(tmp_path: Path) -> None:
    """A record is findable by any of its remote or path aliases."""

    ensure_store(tmp_path)
    reg = Registry.load(tmp_path)
    reg.create("proj-a", remotes=["github.com/x/a"], paths=["/work/a"])

    assert reg.find_by_remote("github.com/x/a") is not None
    assert reg.find_by_path("/work/a") is not None
    assert reg.find_by_remote("github.com/x/missing") is None
    assert reg.find_by_path("/nowhere") is None


def test_add_aliases_deduplicates(tmp_path: Path) -> None:
    """Adding an alias already present does not duplicate it."""

    ensure_store(tmp_path)
    reg = Registry.load(tmp_path)
    reg.create("proj-a", remotes=["r1"], paths=["/p1"])
    reg.add_aliases("proj-a", remotes=["r1", "r2"], paths=["/p1", "/p2"])

    record = reg.find_by_id("proj-a")
    assert record is not None
    assert sorted(record.remotes) == ["r1", "r2"]
    assert sorted(record.paths) == ["/p1", "/p2"]


def test_registry_file_is_owner_only(tmp_path: Path) -> None:
    """The registry file is written with 0600 permissions."""

    ensure_store(tmp_path)
    reg = Registry.load(tmp_path)
    reg.create("proj-a", remotes=[], paths=["/p1"])
    reg.save()

    assert stat.S_IMODE(registry_path(tmp_path).stat().st_mode) == 0o600
    # The file is valid JSON.
    json.loads(registry_path(tmp_path).read_text())


def test_missing_registry_loads_empty(tmp_path: Path) -> None:
    """Loading before any project exists yields an empty registry."""

    ensure_store(tmp_path)
    reg = Registry.load(tmp_path)
    assert reg.find_by_id("anything") is None


def test_merge_moves_memory_and_aliases(tmp_path: Path) -> None:
    """Merging an orphan into its recognised identity moves its memory files and
    folds in its aliases, then removes the orphan entry."""

    ensure_store(tmp_path)
    reg = Registry.load(tmp_path)
    reg.create("orphan", remotes=[], paths=["/old/path"])
    reg.create("canonical", remotes=["github.com/x/a"], paths=["/new/path"])
    reg.save()

    # Seed a memory file under the orphan's project directory.
    orphan_dir = project_dir("orphan", tmp_path)
    orphan_dir.mkdir(parents=True)
    (orphan_dir / "short-term.md").write_text("orphaned note\n", encoding="utf-8")

    reg.merge("orphan", "canonical")
    reg.save()

    reloaded = Registry.load(tmp_path)
    assert reloaded.find_by_id("orphan") is None
    canonical = reloaded.find_by_id("canonical")
    assert canonical is not None
    assert "/old/path" in canonical.paths
    moved = project_dir("canonical", tmp_path) / "short-term.md"
    assert moved.read_text() == "orphaned note\n"
    assert not orphan_dir.exists()
