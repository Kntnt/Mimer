"""Unit tests for the project registry: the store-level record mapping project
ids to their known remotes and paths, plus the merge that repairs an orphaned
project (ADR 0008).
"""

from __future__ import annotations

import json
import stat
from pathlib import Path

from mimer.gitreader import GIT_LEDGER_FILENAME
from mimer.longterm import (
    append_entry,
    daily_log_path,
    is_captured,
    is_digested,
    long_term_dir,
    record_captured,
    record_digested,
    transcripts_dir,
)
from mimer.registry import Registry, project_dir, registry_path
from mimer.shortterm import (
    SECTIONS,
    Entry,
    parse_short_term,
    render_short_term,
    short_term_path,
)
from mimer.store import ensure_store


def _seed_short_term(project_id: str, root: Path, *, notes: list[str]) -> None:
    """Write a canonical short-term memory file whose Notes section holds ``notes``."""

    sections: dict[str, list[Entry]] = {name: [] for name in SECTIONS}
    sections["Notes"] = [Entry("2026-07-10", note) for note in notes]

    path = short_term_path(project_id, root)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(render_short_term(project_id, sections), encoding="utf-8")


def _seed_git_ledger(project_id: str, root: Path, sha: str) -> None:
    """Append one commit sha to a project's git-fold ledger."""

    ledger = long_term_dir(project_id, root) / GIT_LEDGER_FILENAME
    ledger.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write(sha + "\n")


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


def test_merge_of_two_populated_projects_loses_no_entries(tmp_path: Path) -> None:
    """Merging two projects that both hold memory combines every artefact without
    losing an entry, without raising, and without leaving the store half-merged."""

    ensure_store(tmp_path)
    reg = Registry.load(tmp_path)
    reg.create("orphan", remotes=[], paths=["/old/path"])
    reg.create("canonical", remotes=[], paths=["/new/path"])
    reg.save()

    # Populate the orphan with one of every project artefact type.
    _seed_short_term("orphan", tmp_path, notes=["orphan note"])
    append_entry("orphan", "2026-07-10", "- orphan log line\n", tmp_path)
    record_captured("orphan", "turn-orphan", tmp_path)
    record_digested("orphan", "sess-orphan", tmp_path)
    _seed_git_ledger("orphan", tmp_path, "shaorphan")
    (transcripts_dir("orphan", tmp_path)).mkdir(parents=True, exist_ok=True)
    (transcripts_dir("orphan", tmp_path) / "sess-orphan.jsonl").write_text("{}\n", encoding="utf-8")

    # Populate the canonical project so every artefact collides on the same path,
    # including a daily log for the very same day.
    _seed_short_term("canonical", tmp_path, notes=["canonical note"])
    append_entry("canonical", "2026-07-10", "- canonical log line\n", tmp_path)
    record_captured("canonical", "turn-canonical", tmp_path)
    record_digested("canonical", "sess-canonical", tmp_path)
    _seed_git_ledger("canonical", tmp_path, "shacanonical")
    (transcripts_dir("canonical", tmp_path)).mkdir(parents=True, exist_ok=True)
    (transcripts_dir("canonical", tmp_path) / "sess-canonical.jsonl").write_text(
        "{}\n", encoding="utf-8"
    )

    reg.merge("orphan", "canonical")
    reg.save()

    # The orphan is gone from both the registry and the disk.
    reloaded = Registry.load(tmp_path)
    assert reloaded.find_by_id("orphan") is None
    assert not project_dir("orphan", tmp_path).exists()

    # Both sides' short-term entries survive.
    notes = [
        entry.text
        for entry in parse_short_term(short_term_path("canonical", tmp_path).read_text())["Notes"]
    ]
    assert "orphan note" in notes
    assert "canonical note" in notes

    # The overlapping daily log carries both sides' lines.
    daily = daily_log_path("canonical", "2026-07-10", tmp_path).read_text()
    assert "orphan log line" in daily
    assert "canonical log line" in daily

    # Every ledger carries both sides' ids.
    assert is_captured("canonical", "turn-orphan", tmp_path)
    assert is_captured("canonical", "turn-canonical", tmp_path)
    assert is_digested("canonical", "sess-orphan", tmp_path)
    assert is_digested("canonical", "sess-canonical", tmp_path)
    git_ledger = (long_term_dir("canonical", tmp_path) / GIT_LEDGER_FILENAME).read_text().split()
    assert "shaorphan" in git_ledger
    assert "shacanonical" in git_ledger

    # Both sides' archived transcripts survive.
    transcripts = {p.name for p in transcripts_dir("canonical", tmp_path).iterdir()}
    assert transcripts == {"sess-orphan.jsonl", "sess-canonical.jsonl"}


def test_merge_short_term_dedups_entries_present_on_both_sides(tmp_path: Path) -> None:
    """A short-term entry identical on both sides appears once after the merge, and
    each side's unique entries are kept."""

    ensure_store(tmp_path)
    reg = Registry.load(tmp_path)
    reg.create("orphan", remotes=[], paths=["/old/path"])
    reg.create("canonical", remotes=[], paths=["/new/path"])
    reg.save()

    _seed_short_term("orphan", tmp_path, notes=["shared note", "orphan only"])
    _seed_short_term("canonical", tmp_path, notes=["shared note", "canonical only"])

    reg.merge("orphan", "canonical")

    notes = [
        entry.text
        for entry in parse_short_term(short_term_path("canonical", tmp_path).read_text())["Notes"]
    ]
    assert notes.count("shared note") == 1
    assert "orphan only" in notes
    assert "canonical only" in notes
