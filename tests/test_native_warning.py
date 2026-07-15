"""Integration tests for the SessionStart native-memory warning (ADR 0025, #68).

Mimer replaces Claude Code's native auto memory rather than racing it: running
both leaves a forgetting hole, since a fact forgotten or redacted in Mimer can be
silently re-injected by the native one. So at session start Mimer reads the
project's ``.claude/settings.json`` and, while native auto memory is on — or
absent, the default-on state — emits a one-line **warning** naming the
``mimer-manage disable-native-memory`` command. With it explicitly off, no
warning appears. Mimer never flips the switch itself; it only warns.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from mimer.distill import _queue_announcement
from mimer.leakage import queue_consent_request
from mimer.native_memory import SETTINGS_KEY, settings_path
from mimer.store import ensure_store
from tests.harness import run_hook, session_start_payload

# The SessionStart hook subprocess loads the embedding model through the snapshot
# manifest, so the session fixture prefetches it once before the suite runs.
pytestmark = pytest.mark.embedding


def _injected_context(stdout: str) -> str:
    """Extract the injected additionalContext from a SessionStart hook's stdout."""

    payload = json.loads(stdout)
    hook_output = payload["hookSpecificOutput"]
    assert hook_output["hookEventName"] == "SessionStart"
    return str(hook_output["additionalContext"])


def _write_native_setting(project_dir: Path, enabled: bool) -> None:
    """Seed the project's ``.claude/settings.json`` with an explicit switch value."""

    path = settings_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({SETTINGS_KEY: enabled}), encoding="utf-8")


def test_session_start_warns_when_native_memory_default_on(
    store_root: Path, resolve_project: Callable[[Path], str], project_dir: Path
) -> None:
    """With no ``.claude/settings.json`` at all — the default-on state — the warning
    is emitted and names the disable command, so a live native memory is never
    missed (ADR 0025)."""

    ensure_store(store_root)
    resolve_project(project_dir)
    assert not settings_path(project_dir).exists()

    result = run_hook(
        "SessionStart",
        session_start_payload(cwd=str(project_dir)),
        store_root=store_root,
        cwd=project_dir,
    )

    assert result.returncode == 0, result.stderr
    context = _injected_context(result.stdout)
    assert "native auto memory is ON" in context
    assert "mimer-manage disable-native-memory" in context


def test_session_start_warns_when_native_memory_explicitly_on(
    store_root: Path, resolve_project: Callable[[Path], str], project_dir: Path
) -> None:
    """An explicit ``autoMemoryEnabled: true`` produces the warning."""

    ensure_store(store_root)
    resolve_project(project_dir)
    _write_native_setting(project_dir, enabled=True)

    result = run_hook(
        "SessionStart",
        session_start_payload(cwd=str(project_dir)),
        store_root=store_root,
        cwd=project_dir,
    )

    assert result.returncode == 0, result.stderr
    context = _injected_context(result.stdout)
    assert "native auto memory is ON" in context
    assert "mimer-manage disable-native-memory" in context


def test_session_start_is_silent_when_native_memory_off(
    store_root: Path, resolve_project: Callable[[Path], str], project_dir: Path
) -> None:
    """With native auto memory explicitly off, no warning appears — Mimer replaces
    it, and there is nothing left to warn about (ADR 0025)."""

    ensure_store(store_root)
    resolve_project(project_dir)
    _write_native_setting(project_dir, enabled=False)

    result = run_hook(
        "SessionStart",
        session_start_payload(cwd=str(project_dir)),
        store_root=store_root,
        cwd=project_dir,
    )

    assert result.returncode == 0, result.stderr
    context = _injected_context(result.stdout)
    assert "native auto memory" not in context.lower()
    assert "disable-native-memory" not in context


def test_session_start_never_flips_the_switch(
    store_root: Path, resolve_project: Callable[[Path], str], project_dir: Path
) -> None:
    """Emitting the warning must not write the setting: an on (or absent) switch is
    left exactly as it was, since Mimer never flips it silently (ADR 0025)."""

    ensure_store(store_root)
    resolve_project(project_dir)

    run_hook(
        "SessionStart",
        session_start_payload(cwd=str(project_dir)),
        store_root=store_root,
        cwd=project_dir,
    )

    assert not settings_path(project_dir).exists()


def test_session_start_native_warning_coexists_with_consent_and_distilled(
    store_root: Path, resolve_project: Callable[[Path], str], project_dir: Path
) -> None:
    """The native-memory warning fires alongside the pending consent question and
    the distilled-Concept announcement in one session start — the existing notices
    continue to fire, none displaced by the new warning (#68 AC3)."""

    ensure_store(store_root)
    pid = resolve_project(project_dir)
    _queue_announcement(pid, "The team prefers dependency injection", store_root)
    queue_consent_request(pid, "The client's revenue figures are confidential", store_root)

    result = run_hook(
        "SessionStart",
        session_start_payload(cwd=str(project_dir)),
        store_root=store_root,
        cwd=project_dir,
    )

    assert result.returncode == 0, result.stderr
    context = _injected_context(result.stdout)
    assert "native auto memory is ON" in context
    assert "dependency injection" in context.lower()
    assert "revenue figures" in context.lower()
