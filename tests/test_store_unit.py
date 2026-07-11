"""Unit tests for the store-bootstrap, guard and failure-log primitives — the
lowest layer that constrains ticket #1's behaviour.
"""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from mimer import failure_log, guard, store
from mimer.paths import CONFIG_FILENAME, LOG_FILENAME, store_root


def test_store_root_defaults_to_home(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without an override the store root is ``~/.mimer``."""

    monkeypatch.delenv("MIMER_HOME", raising=False)
    assert store_root() == Path.home() / ".mimer"


def test_store_root_honours_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``MIMER_HOME`` overrides the store root so tests never touch the real one."""

    monkeypatch.setenv("MIMER_HOME", str(tmp_path / "s"))
    assert store_root() == tmp_path / "s"


def test_ensure_store_creates_dirs_and_files_with_permissions(tmp_path: Path) -> None:
    """``ensure_store`` creates the root, config and log with 0700/0600 modes."""

    root = tmp_path / "store"

    result = store.ensure_store(root)

    assert result == root
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    config = root / CONFIG_FILENAME
    log = root / LOG_FILENAME
    assert stat.S_IMODE(config.stat().st_mode) == 0o600
    assert stat.S_IMODE(log.stat().st_mode) == 0o600
    assert "[core]" in config.read_text()
    assert log.read_text() == ""


def test_ensure_store_is_idempotent_and_preserves_config(tmp_path: Path) -> None:
    """Re-running never clobbers an edited config or a non-empty log."""

    root = tmp_path / "store"
    store.ensure_store(root)
    (root / CONFIG_FILENAME).write_text("# mine\n")
    (root / LOG_FILENAME).write_text("prior\n")

    store.ensure_store(root)

    assert (root / CONFIG_FILENAME).read_text() == "# mine\n"
    assert (root / LOG_FILENAME).read_text() == "prior\n"


def test_log_failure_appends_single_line(tmp_path: Path) -> None:
    """Each call appends exactly one newline-terminated line to the log."""

    root = store.ensure_store(tmp_path / "store")

    failure_log.log_failure("first problem", root=root)
    failure_log.log_failure("second problem", root=root)

    lines = (root / LOG_FILENAME).read_text().splitlines()
    assert len(lines) == 2
    assert "first problem" in lines[0]
    assert "second problem" in lines[1]


def test_log_failure_flattens_newlines(tmp_path: Path) -> None:
    """A multi-line message stays one physical log line."""

    root = store.ensure_store(tmp_path / "store")

    failure_log.log_failure("line one\nline two", root=root)

    assert len((root / LOG_FILENAME).read_text().splitlines()) == 1


def test_is_guarded_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """The guard is active exactly when its env var is set to a truthy value."""

    monkeypatch.delenv(guard.GUARD_ENV, raising=False)
    assert guard.is_guarded() is False

    monkeypatch.setenv(guard.GUARD_ENV, "1")
    assert guard.is_guarded() is True


def test_spawn_env_sets_guard() -> None:
    """The env handed to a spawned Claude call carries the guard marker."""

    env = guard.spawn_env({"PATH": "/usr/bin"})

    assert env[guard.GUARD_ENV] == "1"
    assert env["PATH"] == "/usr/bin"
