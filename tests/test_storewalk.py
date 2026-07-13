"""Unit tests for the store walk: the read-only enumeration of what the store
holds on disk — project ids (on disk, or known to the registry) and the dates a
project's long-term memory covers (issue #47).
"""

from __future__ import annotations

from pathlib import Path

from mimer.longterm import record_captured, record_digested
from mimer.registry import Registry, project_dir
from mimer.store import ensure_store
from mimer.storewalk import daily_log_days, disk_project_ids, known_project_ids

ROOT = Path(__file__).resolve().parent.parent

# The Store walk glossary entry acceptance criterion pins into CONTEXT.md,
# verbatim and in the plain sibling style of the other Mechanics entries.
CONTEXT_ENTRY = (
    "**Store walk**:\n"
    "The read-only enumeration of what the store holds: project ids (on disk, or "
    "known to the registry) and the dates a project's long-term memory covers. "
    "The one module that walks the projects tree — no other module lists its "
    "directories.\n"
    "_Avoid_: directory scan, file listing, crawl."
)


def _make_project_dir(project_id: str, root: Path) -> Path:
    """Create a project's on-disk memory directory and return it."""

    directory = project_dir(project_id, root)
    directory.mkdir(parents=True)
    return directory


def test_disk_project_ids_empty_when_store_root_missing(tmp_path: Path) -> None:
    """A store root that does not exist has no projects on disk."""

    assert disk_project_ids(tmp_path / "no-store") == []


def test_disk_project_ids_empty_when_projects_dir_missing(tmp_path: Path) -> None:
    """A store with no ``projects/`` directory yet enumerates to an empty list."""

    ensure_store(tmp_path)
    assert disk_project_ids(tmp_path) == []


def test_disk_project_ids_returns_sorted_directory_names(tmp_path: Path) -> None:
    """Every project directory is reported, sorted, regardless of creation order."""

    for project_id in ("proj-c", "proj-a", "proj-b"):
        _make_project_dir(project_id, tmp_path)

    assert disk_project_ids(tmp_path) == ["proj-a", "proj-b", "proj-c"]


def test_disk_project_ids_skips_stray_non_directory_entries(tmp_path: Path) -> None:
    """A stray file sitting directly under ``projects/`` is not a project id."""

    _make_project_dir("proj-a", tmp_path)
    (project_dir("proj-a", tmp_path).parent / "stray.txt").write_text("noise", encoding="utf-8")

    assert disk_project_ids(tmp_path) == ["proj-a"]


def test_known_project_ids_empty_when_store_root_missing(tmp_path: Path) -> None:
    """With neither a registry nor a projects directory, nothing is known."""

    assert known_project_ids(tmp_path / "no-store") == []


def test_known_project_ids_unions_registry_and_disk_deduped_and_sorted(tmp_path: Path) -> None:
    """The union covers all three cases — registry-only, disk-only orphan, and
    both — reporting each id once, sorted."""

    ensure_store(tmp_path)
    registry = Registry.load(tmp_path)
    registry.create("registered-only")
    registry.create("both")
    registry.save()

    _make_project_dir("both", tmp_path)
    _make_project_dir("orphan", tmp_path)

    assert known_project_ids(tmp_path) == ["both", "orphan", "registered-only"]


def test_daily_log_days_empty_when_project_has_no_long_term_memory(tmp_path: Path) -> None:
    """A project directory with no ``long-term/`` folder covers no days."""

    _make_project_dir("proj-a", tmp_path)
    assert daily_log_days("proj-a", tmp_path) == []


def test_daily_log_days_empty_when_project_is_unknown(tmp_path: Path) -> None:
    """A project that was never written to at all covers no days."""

    ensure_store(tmp_path)
    assert daily_log_days("ghost", tmp_path) == []


def test_daily_log_days_returns_sorted_iso_date_stems(tmp_path: Path) -> None:
    """The daily-log stems are returned in chronological (lexical) order."""

    from mimer.longterm import append_entry

    for day in ("2026-07-12", "2026-07-10", "2026-07-11"):
        append_entry("proj-a", day, "- entry\n", tmp_path)

    assert daily_log_days("proj-a", tmp_path) == ["2026-07-10", "2026-07-11", "2026-07-12"]


def test_daily_log_days_ignores_non_daily_log_files(tmp_path: Path) -> None:
    """The dedup ledgers that live alongside the daily logs are not ``.md`` files
    and so are excluded from a project's covered days."""

    from mimer.longterm import append_entry

    append_entry("proj-a", "2026-07-10", "- entry\n", tmp_path)
    record_captured("proj-a", "turn-1", tmp_path)
    record_digested("proj-a", "sess-1", tmp_path)

    assert daily_log_days("proj-a", tmp_path) == ["2026-07-10"]


def test_context_md_carries_the_store_walk_entry() -> None:
    """CONTEXT.md carries the Store walk glossary entry verbatim (issue #47)."""

    assert CONTEXT_ENTRY in (ROOT / "CONTEXT.md").read_text(encoding="utf-8")


def test_only_the_store_walk_lists_the_projects_tree() -> None:
    """No module outside the store walk enumerates the projects tree (issue #48).

    The projects-directory name lives in ``PROJECTS_DIRNAME``; the only two source
    files that may name it are ``storewalk.py``, the sole module that lists the
    tree, and ``registry.py``, which defines the constant and builds a single
    project's path from it. Any other reference means an inline walk survived the
    routing, so this grep is the standing guard the acceptance criteria demand.
    """

    source = ROOT / "src" / "mimer"
    allowed = {"storewalk.py", "registry.py"}
    offenders = sorted(
        path.relative_to(ROOT).as_posix()
        for path in source.rglob("*.py")
        if path.name not in allowed and "PROJECTS_DIRNAME" in path.read_text(encoding="utf-8")
    )

    assert offenders == [], f"projects-tree walk outside the store walk: {offenders}"
