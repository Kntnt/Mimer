"""Unit tests for the project registry: the store-level record mapping project
ids to their known remotes and paths, plus the merge that repairs an orphaned
project (ADR 0008).
"""

from __future__ import annotations

import json
import stat
from dataclasses import asdict
from pathlib import Path

import pytest

from mimer.distill import ANNOUNCEMENT_QUEUE_FILENAME
from mimer.longterm import (
    CAPTURE_LEDGER_FILENAME,
    append_entry,
    daily_log_path,
    is_captured,
    long_term_dir,
    record_captured,
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


def _seed_capture_ledger(project_id: str, root: Path, turn_id: str) -> None:
    """Append one turn id directly to a project's capture ledger.

    A representative append-only dedup ledger for the merge tests, written by hand
    (bypassing :func:`record_captured`) so a test can control the exact bytes — a
    file that ends without a trailing newline, say.
    """

    ledger = long_term_dir(project_id, root) / CAPTURE_LEDGER_FILENAME
    ledger.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write(turn_id + "\n")


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


def test_registry_round_trips_populated_records_through_write_atomic(tmp_path: Path) -> None:
    """A fully populated registry — remotes, paths and per-project settings,
    carrying the provenance identifiers Mimer cites (a git SHA, a ULID, an ISO
    date, remote URLs) plus a secret-shaped setting key — survives a save/load
    cycle field-for-field equal.

    ``save`` persists through the shared ``write_atomic`` primitive (#56). This is
    the positive proof the migration demands: once that primitive redacts at the
    write seam, a false positive on this structural JSON would be silent corruption
    rather than a leak, so the guarantee has to be shown present, not inferred from
    the suite merely staying green. The identifiers seeded here are exactly the
    shape-safe provenance the redaction pass is designed to pass through untouched,
    and the ``api_token`` key proves the JSON quoting keeps a secret-shaped setting
    name from tripping the assigned-secret rule.
    """

    ensure_store(tmp_path)
    reg = Registry.load(tmp_path)
    record = reg.create(
        "proj-a",
        remotes=["github.com/acme/widgets", "git@github.com:acme/widgets.git"],
        paths=["/work/widgets", "/Users/dev/widgets"],
    )
    reg.set_capture("proj-a", enabled=False)
    reg.set_widening("proj-a", participate=False)

    # Seed the shape-safe provenance identifiers and a secret-shaped key into
    # settings, so the round-trip is proven over the exact structural values the
    # redaction pass must pass through byte-identical.
    record.settings.update(
        {
            "cursor": "9f8e7d6c5b4a39281706f5e4d3c2b1a09f8e7d6c",
            "last_ulid": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
            "started": "2026-07-14",
            "api_token": "structural-key-must-survive",
        }
    )
    reg.save()

    original = reg.find_by_id("proj-a")
    reloaded = Registry.load(tmp_path).find_by_id("proj-a")
    assert original is not None and reloaded is not None
    assert asdict(reloaded) == asdict(original)


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
    (transcripts_dir("orphan", tmp_path)).mkdir(parents=True, exist_ok=True)
    (transcripts_dir("orphan", tmp_path) / "sess-orphan.jsonl").write_text("{}\n", encoding="utf-8")

    # Populate the canonical project so every artefact collides on the same path,
    # including a daily log for the very same day.
    _seed_short_term("canonical", tmp_path, notes=["canonical note"])
    append_entry("canonical", "2026-07-10", "- canonical log line\n", tmp_path)
    record_captured("canonical", "turn-canonical", tmp_path)
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

    # The capture ledger carries both sides' ids.
    assert is_captured("canonical", "turn-orphan", tmp_path)
    assert is_captured("canonical", "turn-canonical", tmp_path)

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

    # Seed both sides so short-term.md and the capture ledger collide, then loosen
    # the target copies to 0644 so the assertion fails unless the merge tightens them.
    _seed_short_term("orphan", tmp_path, notes=["orphan note"])
    _seed_short_term("canonical", tmp_path, notes=["canonical note"])
    _seed_capture_ledger("orphan", tmp_path, "turn-orphan")
    _seed_capture_ledger("canonical", tmp_path, "turn-canonical")
    canonical_short_term = short_term_path("canonical", tmp_path)
    canonical_ledger = long_term_dir("canonical", tmp_path) / CAPTURE_LEDGER_FILENAME
    canonical_short_term.chmod(0o644)
    canonical_ledger.chmod(0o644)

    reg.merge("orphan", "canonical")

    assert stat.S_IMODE(canonical_short_term.stat().st_mode) == 0o600
    assert stat.S_IMODE(canonical_ledger.stat().st_mode) == 0o600


def test_merge_creates_target_subdirs_owner_only(tmp_path: Path) -> None:
    """A subdirectory the merge creates on the target — present only on the orphan
    — is 0700, and a target subdirectory loosened beforehand is re-tightened, so a
    merge never widens the store's owner-only directory invariant (ADR 0013)."""

    ensure_store(tmp_path)
    reg = Registry.load(tmp_path)
    reg.create("orphan", remotes=[], paths=["/old/path"])
    reg.create("canonical", remotes=[], paths=["/new/path"])
    reg.save()

    # transcripts/ exists only on the orphan, so the merge creates it fresh on the
    # target; long-term/ exists on both but is loosened on the target, so the merge
    # must re-tighten it rather than leave it group/world-traversable.
    transcripts_dir("orphan", tmp_path).mkdir(parents=True, exist_ok=True)
    (transcripts_dir("orphan", tmp_path) / "sess-orphan.jsonl").write_text("{}\n", encoding="utf-8")
    _seed_capture_ledger("orphan", tmp_path, "turn-orphan")
    _seed_capture_ledger("canonical", tmp_path, "turn-canonical")
    long_term_dir("canonical", tmp_path).chmod(0o755)

    reg.merge("orphan", "canonical")

    assert stat.S_IMODE(transcripts_dir("canonical", tmp_path).stat().st_mode) == 0o700
    assert stat.S_IMODE(long_term_dir("canonical", tmp_path).stat().st_mode) == 0o700


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
    orphan_ledger = long_term_dir("orphan", tmp_path) / CAPTURE_LEDGER_FILENAME
    orphan_ledger.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    orphan_ledger.write_text("turn-orphan\n", encoding="utf-8")
    canonical_ledger = long_term_dir("canonical", tmp_path) / CAPTURE_LEDGER_FILENAME
    canonical_ledger.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    canonical_ledger.write_text("turn-canonical", encoding="utf-8")

    reg.merge("orphan", "canonical")

    ids = canonical_ledger.read_text().split()
    assert ids == ["turn-canonical", "turn-orphan"]


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

    # Seed the capture ledger on both sides so it is the one artefact the merge folds.
    _seed_capture_ledger("orphan", tmp_path, "turn-orphan")
    _seed_capture_ledger("canonical", tmp_path, "turn-canonical")
    target_ledger = long_term_dir("canonical", tmp_path) / CAPTURE_LEDGER_FILENAME

    # Simulate a concurrent capture: the instant the merge reads the target ledger,
    # an out-of-band O_APPEND writer lands a new id on it. A read-modify-write merge
    # would overwrite it; an O_APPEND fold keeps it.
    original_read_text = Path.read_text
    state = {"fired": False}

    def read_text_then_concurrent_append(self: Path, *args: object, **kwargs: object) -> str:
        content = original_read_text(self, *args, **kwargs)  # type: ignore[arg-type]
        if self == target_ledger and not state["fired"]:
            state["fired"] = True
            with self.open("a", encoding="utf-8") as handle:
                handle.write("turn-concurrent\n")
        return content

    monkeypatch.setattr(Path, "read_text", read_text_then_concurrent_append)

    reg.merge("orphan", "canonical")

    ids = target_ledger.read_text().split()
    assert "turn-canonical" in ids
    assert "turn-orphan" in ids
    assert "turn-concurrent" in ids


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
    for project_id in ("orphan", "canonical"):
        transcripts_dir(project_id, tmp_path).mkdir(parents=True, exist_ok=True)
        transcript = transcripts_dir(project_id, tmp_path) / "sess-shared.jsonl"
        transcript.write_text(f'{{"who":"{project_id}"}}\n', encoding="utf-8")

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
    orphan_queue = project_dir("orphan", tmp_path) / ANNOUNCEMENT_QUEUE_FILENAME
    orphan_queue.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    orphan_queue.write_text("orphan title\n", encoding="utf-8")
    canonical_queue = project_dir("canonical", tmp_path) / ANNOUNCEMENT_QUEUE_FILENAME
    canonical_queue.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    canonical_queue.write_text("canonical title\n", encoding="utf-8")

    reg.merge("orphan", "canonical")

    titles = canonical_queue.read_text().splitlines()
    assert "orphan title" in titles
    assert "canonical title" in titles


def test_merge_carries_source_settings_when_target_has_none(
    tmp_path: Path,
) -> None:
    """A source's per-project settings survive the merge when the target has not
    set its own: a capture the user paused on the source stays paused (#34)."""

    ensure_store(tmp_path)
    reg = Registry.load(tmp_path)
    reg.create("orphan", remotes=[], paths=["/old/path"])
    reg.create("canonical", remotes=[], paths=["/new/path"])

    # The user paused capture on the orphan; the canonical record has not, so the
    # merge must adopt the orphan's.
    reg.set_capture("orphan", enabled=False)

    reg.merge("orphan", "canonical")

    assert reg.capture_enabled("canonical") is False


def test_merge_prefers_target_settings_on_conflict(tmp_path: Path) -> None:
    """When both sides set the same control, the target's explicitly-set value
    wins — a deliberate binding is never silently overridden by a retired orphan's
    stale value (#34)."""

    ensure_store(tmp_path)
    reg = Registry.load(tmp_path)
    reg.create("orphan", remotes=[], paths=["/old/path"])
    reg.create("canonical", remotes=[], paths=["/new/path"])

    # Both sides set capture; the target's value must survive. The orphan
    # additionally excludes itself from widening, a control the target never set,
    # so that one is adopted.
    reg.set_capture("orphan", enabled=False)
    reg.set_widening("orphan", participate=False)
    reg.set_capture("canonical", enabled=True)

    reg.merge("orphan", "canonical")

    assert reg.capture_enabled("canonical") is True
    assert reg.is_widenable("canonical") is False
