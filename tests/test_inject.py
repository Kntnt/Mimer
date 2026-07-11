"""Integration tests for the SessionStart injection hook (Stage 1): with a
seeded short-term memory the hook emits the framed, announced snapshot; a
compact source re-injects; an unknown project is well-formed; and no other hook
injects.
"""

from __future__ import annotations

import json
from pathlib import Path

from mimer.project import resolve
from mimer.shortterm import short_term_path
from tests.harness import run_hook, session_start_payload, stop_payload


def _injected_context(stdout: str) -> str:
    """Extract the injected additionalContext from a SessionStart hook's stdout."""

    payload = json.loads(stdout)
    hook_output = payload["hookSpecificOutput"]
    assert hook_output["hookEventName"] == "SessionStart"
    return str(hook_output["additionalContext"])


def _seed_short_term(store_root: Path, cwd: Path, body: str) -> None:
    """Resolve ``cwd`` to its project and write a seeded short-term memory file."""

    resolution = resolve(cwd, root=store_root)
    assert resolution.project_id is not None
    path = short_term_path(resolution.project_id, store_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_seeded_snapshot_and_announcement_emitted(store_root: Path, project_dir: Path) -> None:
    """A seeded short-term file is injected with its content and a one-line
    announcement."""

    _seed_short_term(
        store_root,
        project_dir,
        "## Active threads\n\n- [2026-06-20] rewiring the recall path\n",
    )

    result = run_hook(
        "SessionStart",
        session_start_payload(source="startup", cwd=str(project_dir)),
        store_root=store_root,
        cwd=project_dir,
    )

    assert result.returncode == 0, result.stderr
    context = _injected_context(result.stdout)
    assert "rewiring the recall path" in context
    assert "Mimer: injected short-term memory" in context


def test_entries_carry_dates_and_ages(store_root: Path, project_dir: Path) -> None:
    """Injected entries keep their dates and are labelled with their age."""

    _seed_short_term(
        store_root,
        project_dir,
        "## Notes\n\n- [2026-06-20] chose sqlite-vec for the index\n",
    )

    result = run_hook(
        "SessionStart",
        session_start_payload(cwd=str(project_dir)),
        store_root=store_root,
        cwd=project_dir,
    )

    context = _injected_context(result.stdout)
    assert "[2026-06-20]" in context
    assert "ago)" in context


def test_compact_source_reinjects(store_root: Path, project_dir: Path) -> None:
    """A compact-source SessionStart re-injects the snapshot (ADR 0016)."""

    _seed_short_term(
        store_root, project_dir, "## Active threads\n\n- [2026-07-01] compaction test\n"
    )

    result = run_hook(
        "SessionStart",
        session_start_payload(source="compact", cwd=str(project_dir)),
        store_root=store_root,
        cwd=project_dir,
    )

    assert result.returncode == 0, result.stderr
    assert "compaction test" in _injected_context(result.stdout)


def test_other_mid_context_paths_do_not_inject(store_root: Path, project_dir: Path) -> None:
    """No non-SessionStart hook injects a snapshot — only SessionStart does."""

    _seed_short_term(store_root, project_dir, "## Notes\n\n- [2026-07-01] secret thread\n")

    result = run_hook(
        "Stop", stop_payload(cwd=str(project_dir)), store_root=store_root, cwd=project_dir
    )

    assert result.returncode == 0, result.stderr
    assert "secret thread" not in result.stdout
    assert result.stdout.strip() == ""


def test_unknown_project_injects_empty_but_well_formed(store_root: Path, project_dir: Path) -> None:
    """An unknown project injects a well-formed empty snapshot without error."""

    result = run_hook(
        "SessionStart",
        session_start_payload(cwd=str(project_dir)),
        store_root=store_root,
        cwd=project_dir,
    )

    assert result.returncode == 0, result.stderr
    context = _injected_context(result.stdout)
    assert "no short-term memory yet" in context
