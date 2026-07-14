"""Tests for user-facing capture controls (issue #35): a session-level pause and
the per-project settings ADR 0013 promises — capture on/off, distill-to-global
on/off, and participation in widened recall — surfaced through ``mimer-manage``
and honoured by the capture, boundary pass, distillation and recall paths.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from mimer import manage
from mimer.bundle import list_concepts
from mimer.capture import capture_from_payload
from mimer.distill import distill_fact
from mimer.pause import clear_paused, is_paused, set_paused
from mimer.registry import Registry
from mimer.store import ensure_store
from tests.harness import run_hook, session_end_payload, session_start_payload
from tests.transcript_fixture import write_transcript


def _payload(cwd: Path, transcript: Path) -> dict[str, object]:
    """A representative Stop payload pointing at a seeded transcript."""

    return {
        "session_id": "test-session",
        "hook_event_name": "Stop",
        "stop_hook_active": False,
        "cwd": str(cwd),
        "transcript_path": str(transcript),
    }


def _seeded_stop(project_dir: Path, text: str) -> dict[str, object]:
    """Build a Stop payload whose one exchange contains ``text``."""

    transcript = write_transcript(
        project_dir / f"{abs(hash(text))}.jsonl",
        [(f"user: {text}", text, "2026-07-11T10:00:00Z")],
    )
    return _payload(project_dir, transcript)


# --- Session-level pause -----------------------------------------------------


def test_pause_marker_round_trips(store_root: Path) -> None:
    """Pause is off by default, on after ``set_paused``, off again after clear."""

    assert not is_paused(store_root)

    set_paused(store_root)
    assert is_paused(store_root)

    clear_paused(store_root)
    assert not is_paused(store_root)


def test_paused_session_captures_nothing(
    store_root: Path, resolve_project: Callable[[Path], str], project_dir: Path
) -> None:
    """While paused, the Stop hook's capture records nothing to long-term memory."""

    ensure_store(store_root)
    set_paused(store_root)

    result = capture_from_payload(_seeded_stop(project_dir, "the secret plan"), root=store_root)

    assert result.status == "paused"
    pid = resolve_project(project_dir)
    long_term = store_root / "projects" / pid / "long-term"
    assert not long_term.exists() or not any(long_term.iterdir())


def test_resume_restores_capture(store_root: Path, project_dir: Path) -> None:
    """Capture is suppressed while paused and records again only after resume.

    Asserting the paused outcome first makes the capture pause-gate load-bearing:
    were the gate removed, the mid-pause capture would already record, so this
    test — not just ``clear_paused`` — constrains the pause behaviour.
    """

    ensure_store(store_root)

    set_paused(store_root)
    paused = capture_from_payload(_seeded_stop(project_dir, "off the record"), root=store_root)
    assert paused.status == "paused"

    clear_paused(store_root)
    resumed = capture_from_payload(_seeded_stop(project_dir, "back on the record"), root=store_root)
    assert resumed.status == "captured"


def test_session_end_leaves_the_pause_in_place(store_root: Path, project_dir: Path) -> None:
    """A session ending never lifts the store-wide pause (#35).

    The pause is store-wide, so an unrelated concurrent session reaching
    SessionEnd must not clear a pause it never asked for — only an explicit
    resume does. Were SessionEnd to clear it, that session's next Stop would
    record the sensitive work the pause was meant to protect.
    """

    ensure_store(store_root)
    set_paused(store_root)

    result = run_hook(
        "SessionEnd",
        session_end_payload(cwd=str(project_dir)),
        store_root=store_root,
        cwd=project_dir,
    )

    assert result.returncode == 0, result.stderr
    assert is_paused(store_root)


def test_session_start_announces_a_standing_pause(
    store_root: Path, resolve_project: Callable[[Path], str], project_dir: Path
) -> None:
    """SessionStart announces a store-wide pause, so a forgotten one is visible (#35)."""

    ensure_store(store_root)
    resolve_project(project_dir)
    set_paused(store_root)

    result = run_hook(
        "SessionStart",
        session_start_payload(cwd=str(project_dir)),
        store_root=store_root,
        cwd=project_dir,
    )

    assert result.returncode == 0, result.stderr
    assert "PAUSED" in result.stdout


def test_health_reports_a_standing_pause(store_root: Path) -> None:
    """A standing pause shows in store health, so it is never a silent blackout (#35)."""

    ensure_store(store_root)
    assert manage.store_health(store_root).paused is False

    set_paused(store_root)
    assert manage.store_health(store_root).paused is True


# --- Per-project setting: capture on/off -------------------------------------


def test_capture_disabled_project_records_nothing(
    store_root: Path, resolve_project: Callable[[Path], str], project_dir: Path
) -> None:
    """A project with capture disabled records nothing from the Stop hook."""

    ensure_store(store_root)
    pid = resolve_project(project_dir)
    registry = Registry.load(store_root)
    registry.set_capture(pid, enabled=False)
    registry.save()

    result = capture_from_payload(_seeded_stop(project_dir, "would-be captured"), root=store_root)

    assert result.status == "capture-disabled"


def test_capture_enabled_by_default(store_root: Path, project_dir: Path) -> None:
    """A fresh project captures, since capture defaults on."""

    ensure_store(store_root)

    result = capture_from_payload(_seeded_stop(project_dir, "on the record"), root=store_root)

    assert result.status == "captured"


def test_capture_setting_round_trips_through_the_command(
    store_root: Path, project_dir: Path
) -> None:
    """Setting capture off then on via the management surface is honoured by capture."""

    ensure_store(store_root)

    off = manage.set_project_setting("capture", False, cwd=project_dir, root=store_root)
    assert off is not None and off.capture is False
    shown = manage.project_settings(cwd=project_dir, root=store_root)
    assert shown is not None and shown.capture is False
    disabled = capture_from_payload(_seeded_stop(project_dir, "hidden"), root=store_root)
    assert disabled.status == "capture-disabled"

    manage.set_project_setting("capture", True, cwd=project_dir, root=store_root)
    enabled = capture_from_payload(_seeded_stop(project_dir, "visible"), root=store_root)
    assert enabled.status == "captured"


def test_health_reports_capture_disabled_projects(
    store_root: Path, resolve_project: Callable[[Path], str], project_dir: Path
) -> None:
    """A project with capture off is enumerated in store health (#35).

    A per-project ``capture off`` is a standing, indefinite suppression, so — like
    a pause — it must be auditable in ``mimer-manage health`` rather than a silent
    per-project blackout discoverable only from inside that exact project.
    """

    ensure_store(store_root)
    pid = resolve_project(project_dir)
    assert manage.store_health(store_root).capture_disabled_projects == []

    registry = Registry.load(store_root)
    registry.set_capture(pid, enabled=False)
    registry.save()

    assert manage.store_health(store_root).capture_disabled_projects == [pid]


def test_session_start_announces_a_capture_disabled_project(
    store_root: Path, resolve_project: Callable[[Path], str], project_dir: Path
) -> None:
    """SessionStart announces this project's standing capture-off, for parity with
    the pause notice, so a forgotten one is visible rather than silent (#35)."""

    ensure_store(store_root)
    pid = resolve_project(project_dir)
    registry = Registry.load(store_root)
    registry.set_capture(pid, enabled=False)
    registry.save()

    result = run_hook(
        "SessionStart",
        session_start_payload(cwd=str(project_dir)),
        store_root=store_root,
        cwd=project_dir,
    )

    assert result.returncode == 0, result.stderr
    assert "capture is OFF for this project" in result.stdout


# --- Per-project setting: participation in widened recall --------------------


def test_widening_setting_round_trips_through_the_command(
    store_root: Path, resolve_project: Callable[[Path], str], project_dir: Path
) -> None:
    """Turning widening off excludes the project from widened recall (ADR 0013)."""

    ensure_store(store_root)
    pid = resolve_project(project_dir)
    assert Registry.load(store_root).is_widenable(pid)

    settings = manage.set_project_setting("widening", False, cwd=project_dir, root=store_root)

    assert settings is not None and settings.widening is False
    assert not Registry.load(store_root).is_widenable(pid)


# --- Per-project setting: distill-to-global on/off ---------------------------


def test_distill_to_global_off_downgrades_scope(
    store_root: Path, resolve_project: Callable[[Path], str], project_dir: Path
) -> None:
    """With distill-to-global off, a global distillation lands project-scoped."""

    ensure_store(store_root)
    pid = resolve_project(project_dir)
    registry = Registry.load(store_root)
    registry.set_distill_to_global(pid, enabled=False)
    registry.save()

    result = distill_fact(
        text="We standardise on ISO-8601 dates everywhere.",
        project_id=pid,
        scope="global",
        root=store_root,
    )

    assert result.slug is not None
    concept = next(c for c in list_concepts(store_root) if c.slug == result.slug)
    assert concept.scope == "project"


def test_distill_to_global_on_keeps_global_scope(
    store_root: Path, resolve_project: Callable[[Path], str], project_dir: Path
) -> None:
    """With distill-to-global on (the default), a global distillation stays global."""

    ensure_store(store_root)
    pid = resolve_project(project_dir)

    result = distill_fact(
        text="The user prefers concise commit messages.",
        project_id=pid,
        scope="global",
        root=store_root,
    )

    assert result.slug is not None
    concept = next(c for c in list_concepts(store_root) if c.slug == result.slug)
    assert concept.scope == "global"


# --- Management-surface CLI --------------------------------------------------


def test_manage_pause_and_resume_cli(store_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``mimer-manage pause`` and ``resume`` toggle the session-level pause."""

    monkeypatch.setenv("MIMER_HOME", str(store_root))

    manage.main(["pause"])
    assert is_paused(store_root)

    manage.main(["resume"])
    assert not is_paused(store_root)


def test_manage_settings_cli_shows_and_sets(
    store_root: Path,
    resolve_project: Callable[[Path], str],
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``mimer-manage settings`` shows and updates a project's per-project settings.

    The show path is content-asserted, not merely exit-code-checked: distill-to-global
    must be genuinely *viewable* through the management surface (AC2: #35), so a bug
    that dropped it from the displayed settings would fail here rather than pass.
    """

    monkeypatch.setenv("MIMER_HOME", str(store_root))
    monkeypatch.chdir(project_dir)

    # The default (on) is reflected in the displayed settings, not just implied.
    assert manage.main(["settings"]) == 0
    assert "distill-to-global on" in capsys.readouterr().out

    assert manage.main(["settings", "distill-to-global", "off"]) == 0

    pid = resolve_project(project_dir)
    assert not Registry.load(store_root).distill_to_global_enabled(pid)

    # The new value is viewable through the same surface that set it.
    assert manage.main(["settings"]) == 0
    assert "distill-to-global off" in capsys.readouterr().out


# --- Concurrent registry safety ----------------------------------------------


def test_set_project_setting_returns_none_when_project_merged_away(
    store_root: Path, project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A project removed by a concurrent merge in the reload window yields None,
    not a KeyError traceback (#35)."""

    from mimer.project import Resolution, ResolutionStatus

    ensure_store(store_root)

    # Simulate resolve() naming a project that a concurrent merge (ADR 0008) has
    # since deleted from the registry, so the record is gone at reload time.
    monkeypatch.setattr(
        manage,
        "resolve",
        lambda *args, **kwargs: Resolution(ResolutionStatus.RECOGNISED, "merged-away"),
    )

    result = manage.set_project_setting("capture", False, cwd=project_dir, root=store_root)

    assert result is None


# --- config.toml removed -----------------------------------------------------


def test_ensure_store_does_not_create_config_toml(store_root: Path) -> None:
    """Per-project settings live in the registry, so no created-but-ignored
    ``config.toml`` remains (issue #35)."""

    ensure_store(store_root)

    assert not (store_root / "config.toml").exists()
