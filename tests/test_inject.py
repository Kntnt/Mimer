"""Integration tests for the SessionStart injection hook (Stage 1): with a
seeded short-term memory the hook emits the framed, announced snapshot; a
compact source re-injects; an unknown project is well-formed; and no other hook
injects.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mimer.project import resolve
from mimer.registry import Registry
from mimer.shortterm import short_term_path
from mimer.store import ensure_store
from tests.harness import run_hook, session_start_payload, stop_payload

# Every test here loads the embedding model (directly or via a hook subprocess),
# so the session fixture prefetches it once before the suite runs (conftest.py).
pytestmark = pytest.mark.embedding


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


def test_distillation_announcement_survives_a_later_failure(
    store_root: Path, project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The "Distilled since last session" notice is not lost when a step after the
    drain fails: the queue is cleared only once the snapshot is emitted, so a
    failure re-announces next session rather than dropping the notice for good —
    at-least-once, never zero (ADR 0014, #40)."""

    import mimer.hooks.session_start as session_start
    from mimer.distill import _queue_announcement, _queue_path

    ensure_store(store_root)
    monkeypatch.setenv("MIMER_HOME", str(store_root))
    resolution = resolve(project_dir, root=store_root)
    assert resolution.project_id is not None
    pid = resolution.project_id
    _queue_announcement(pid, "A distilled concept", store_root)

    # Force a failure strictly after the queue would be drained: snapshot rendering
    # raises, standing in for any post-drain step that can fail.
    def boom(*_: object, **__: object) -> str:
        raise RuntimeError("snapshot build failed")

    monkeypatch.setattr(session_start, "build_snapshot", boom)

    with pytest.raises(RuntimeError):
        session_start.handle({"cwd": str(project_dir), "source": "startup"})

    queue = _queue_path(pid, store_root)
    assert queue.exists()
    assert "A distilled concept" in queue.read_text(encoding="utf-8")


def test_needs_confirmation_injection_names_confirm_command(
    store_root: Path, tmp_path: Path
) -> None:
    """When identity needs confirmation the injection refuses, but the refusal
    names the exact command and candidate id to run — turning a dead end into a
    resolvable state (#34)."""

    ensure_store(store_root)
    registry = Registry.load(store_root)
    registry.create("secret-client", paths=[str((tmp_path / "orig").resolve())])
    registry.save()

    clone = tmp_path / "clone"
    clone.mkdir()
    (clone / ".mimer").write_text("secret-client\n", encoding="utf-8")

    result = run_hook(
        "SessionStart",
        session_start_payload(cwd=str(clone)),
        store_root=store_root,
        cwd=clone,
    )

    assert result.returncode == 0, result.stderr
    context = _injected_context(result.stdout)
    assert "needs" in context and "confirmation" in context
    assert "mimer-manage confirm secret-client" in context
