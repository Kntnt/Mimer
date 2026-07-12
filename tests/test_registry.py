"""Unit tests for the project registry: the store-level record mapping project
ids to their known remotes and paths, plus the merge that repairs an orphaned
project (ADR 0008).
"""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from mimer.distill import DISTILLED_QUEUE_FILENAME
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


def test_merge_leaves_combined_files_owner_only(tmp_path: Path) -> None:
    """A file combined during a merge ends up 0600, even when the target copy was
    seeded group/world-readable — the merge must not widen the store's owner-only
    invariant (ADR 0011)."""

    ensure_store(tmp_path)
    reg = Registry.load(tmp_path)
    reg.create("orphan", remotes=[], paths=["/old/path"])
    reg.create("canonical", remotes=[], paths=["/new/path"])
    reg.save()

    # Seed both sides so short-term.md and the git ledger collide, then loosen the
    # target copies to 0644 so the assertion fails unless the merge tightens them.
    _seed_short_term("orphan", tmp_path, notes=["orphan note"])
    _seed_short_term("canonical", tmp_path, notes=["canonical note"])
    _seed_git_ledger("orphan", tmp_path, "shaorphan")
    _seed_git_ledger("canonical", tmp_path, "shacanonical")
    canonical_short_term = short_term_path("canonical", tmp_path)
    canonical_ledger = long_term_dir("canonical", tmp_path) / GIT_LEDGER_FILENAME
    canonical_short_term.chmod(0o644)
    canonical_ledger.chmod(0o644)

    reg.merge("orphan", "canonical")

    assert stat.S_IMODE(canonical_short_term.stat().st_mode) == 0o600
    assert stat.S_IMODE(canonical_ledger.stat().st_mode) == 0o600


def test_merge_inserts_seam_newline_when_target_lacks_one(tmp_path: Path) -> None:
    """Concatenating onto a target whose last record has no trailing newline keeps
    the target's last line and the source's first line distinct rather than fusing
    them into one."""

    ensure_store(tmp_path)
    reg = Registry.load(tmp_path)
    reg.create("orphan", remotes=[], paths=["/old/path"])
    reg.create("canonical", remotes=[], paths=["/new/path"])
    reg.save()

    # Write the target ledger without a trailing newline so the concatenation must
    # supply the seam itself; the source ends normally.
    orphan_ledger = long_term_dir("orphan", tmp_path) / GIT_LEDGER_FILENAME
    orphan_ledger.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    orphan_ledger.write_text("shaorphan\n", encoding="utf-8")
    canonical_ledger = long_term_dir("canonical", tmp_path) / GIT_LEDGER_FILENAME
    canonical_ledger.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    canonical_ledger.write_text("shacanonical", encoding="utf-8")

    reg.merge("orphan", "canonical")

    shas = canonical_ledger.read_text().split()
    assert shas == ["shacanonical", "shaorphan"]


def test_merge_fold_preserves_a_concurrent_append(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A record a producer appends to the target while the merge is folding a
    colliding append-only artefact survives: the merge folds with ``O_APPEND``
    rather than a read-modify-write, so it can neither clobber nor be clobbered by
    a concurrent lockless appender (ADR 0011)."""

    ensure_store(tmp_path)
    reg = Registry.load(tmp_path)
    reg.create("orphan", remotes=[], paths=["/old/path"])
    reg.create("canonical", remotes=[], paths=["/new/path"])
    reg.save()

    # Seed the git ledger on both sides so it is the one artefact the merge folds.
    _seed_git_ledger("orphan", tmp_path, "shaorphan")
    _seed_git_ledger("canonical", tmp_path, "shacanonical")
    target_ledger = long_term_dir("canonical", tmp_path) / GIT_LEDGER_FILENAME

    # Simulate a concurrent git-fold: the instant the merge reads the target
    # ledger, an out-of-band O_APPEND writer lands a new sha on it. A read-modify-
    # write merge would overwrite it; an O_APPEND fold keeps it.
    original_read_text = Path.read_text
    state = {"fired": False}

    def read_text_then_concurrent_append(self: Path, *args: object, **kwargs: object) -> str:
        content = original_read_text(self, *args, **kwargs)  # type: ignore[arg-type]
        if self == target_ledger and not state["fired"]:
            state["fired"] = True
            with self.open("a", encoding="utf-8") as handle:
                handle.write("shaconcurrent\n")
        return content

    monkeypatch.setattr(Path, "read_text", read_text_then_concurrent_append)

    reg.merge("orphan", "canonical")

    shas = target_ledger.read_text().split()
    assert "shacanonical" in shas
    assert "shaorphan" in shas
    assert "shaconcurrent" in shas


def test_merge_folds_a_same_named_transcript(tmp_path: Path) -> None:
    """Two transcripts sharing a filename on both sides are concatenated line for
    line rather than one overwriting the other, so neither session's record is
    lost."""

    ensure_store(tmp_path)
    reg = Registry.load(tmp_path)
    reg.create("orphan", remotes=[], paths=["/old/path"])
    reg.create("canonical", remotes=[], paths=["/new/path"])
    reg.save()

    # Both sides archived a transcript under the very same filename, so the merge
    # must combine the two rather than let one clobber the other.
    for project_id, line in (("orphan", '{"who":"orphan"}\n'), ("canonical", '{"who":"canonical"}\n')):
        transcripts_dir(project_id, tmp_path).mkdir(parents=True, exist_ok=True)
        (transcripts_dir(project_id, tmp_path) / "sess-shared.jsonl").write_text(
            line, encoding="utf-8"
        )

    reg.merge("orphan", "canonical")

    lines = (transcripts_dir("canonical", tmp_path) / "sess-shared.jsonl").read_text().splitlines()
    assert '{"who":"orphan"}' in lines
    assert '{"who":"canonical"}' in lines


def test_merge_keeps_membership_for_a_ledger_id_on_both_sides(tmp_path: Path) -> None:
    """When the same id is recorded on both sides, membership survives the merge:
    concatenating the append-only ledgers may duplicate the shared line, which is
    harmless for the ``is_captured`` set, and each side's unique id is kept."""

    ensure_store(tmp_path)
    reg = Registry.load(tmp_path)
    reg.create("orphan", remotes=[], paths=["/old/path"])
    reg.create("canonical", remotes=[], paths=["/new/path"])
    reg.save()

    # Record one shared turn on both sides plus a unique turn on each.
    record_captured("orphan", "turn-shared", tmp_path)
    record_captured("orphan", "turn-orphan", tmp_path)
    record_captured("canonical", "turn-shared", tmp_path)
    record_captured("canonical", "turn-canonical", tmp_path)

    reg.merge("orphan", "canonical")

    assert is_captured("canonical", "turn-shared", tmp_path)
    assert is_captured("canonical", "turn-orphan", tmp_path)
    assert is_captured("canonical", "turn-canonical", tmp_path)


def test_merge_concatenates_colliding_distilled_queues(tmp_path: Path) -> None:
    """A ``.distilled-queue`` present on both sides is concatenated, so no queued
    announcement title is lost when the projects merge."""

    ensure_store(tmp_path)
    reg = Registry.load(tmp_path)
    reg.create("orphan", remotes=[], paths=["/old/path"])
    reg.create("canonical", remotes=[], paths=["/new/path"])
    reg.save()

    # Seed the top-level distilled queue on both sides so it collides at the
    # project-dir root rather than under long-term/.
    orphan_queue = project_dir("orphan", tmp_path) / DISTILLED_QUEUE_FILENAME
    orphan_queue.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    orphan_queue.write_text("orphan title\n", encoding="utf-8")
    canonical_queue = project_dir("canonical", tmp_path) / DISTILLED_QUEUE_FILENAME
    canonical_queue.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    canonical_queue.write_text("canonical title\n", encoding="utf-8")

    reg.merge("orphan", "canonical")

    titles = canonical_queue.read_text().splitlines()
    assert "orphan title" in titles
    assert "canonical title" in titles
