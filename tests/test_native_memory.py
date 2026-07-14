"""Tests for the native auto-memory read/write seam (issue #64, ADR 0025).

The seam reads Claude Code's ``autoMemoryEnabled`` from a project's
``.claude/settings.json`` — absent meaning on, since it defaults on — and, only
on request, writes it to ``false`` while preserving every other setting. Reads
never mutate; a write never clobbers or reorders the keys already in the file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mimer.native_memory import (
    SETTINGS_KEY,
    disable_native_memory,
    is_native_memory_enabled,
    settings_path,
)


def _write_settings(project_dir: Path, content: str) -> Path:
    """Seed a project's ``.claude/settings.json`` with raw ``content``."""

    path = project_dir / ".claude" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# --- Reading: on / off / absent (treated as on) ------------------------------


def test_absent_settings_file_reports_enabled(project_dir: Path) -> None:
    """No ``.claude/settings.json`` at all means native memory is on (default)."""

    assert is_native_memory_enabled(project_dir) is True


def test_absent_key_reports_enabled(project_dir: Path) -> None:
    """A settings file without the key means native memory is on (default)."""

    _write_settings(project_dir, json.dumps({"someOther": "value"}))

    assert is_native_memory_enabled(project_dir) is True


def test_explicit_false_reports_disabled(project_dir: Path) -> None:
    """``autoMemoryEnabled: false`` reports native memory as off."""

    _write_settings(project_dir, json.dumps({SETTINGS_KEY: False}))

    assert is_native_memory_enabled(project_dir) is False


def test_explicit_true_reports_enabled(project_dir: Path) -> None:
    """``autoMemoryEnabled: true`` reports native memory as on."""

    _write_settings(project_dir, json.dumps({SETTINGS_KEY: True}))

    assert is_native_memory_enabled(project_dir) is True


def test_malformed_settings_reports_enabled(project_dir: Path) -> None:
    """Unparseable settings report enabled — the caller warns rather than misses
    a native memory it cannot confirm is off, and the read stays non-mutating."""

    path = _write_settings(project_dir, "{ not valid json")
    before = path.read_bytes()

    assert is_native_memory_enabled(project_dir) is True
    assert path.read_bytes() == before


# --- Reading never mutates ---------------------------------------------------


def test_read_does_not_create_the_file(project_dir: Path) -> None:
    """Reading an absent settings file creates nothing on disk."""

    is_native_memory_enabled(project_dir)

    assert not settings_path(project_dir).exists()
    assert not (project_dir / ".claude").exists()


def test_read_does_not_modify_an_existing_file(project_dir: Path) -> None:
    """Reading an existing settings file leaves it byte-for-byte unchanged."""

    path = _write_settings(project_dir, json.dumps({SETTINGS_KEY: True, "keep": 1}))
    before = path.read_bytes()

    is_native_memory_enabled(project_dir)

    assert path.read_bytes() == before


# --- Writing: set false, preserve everything else, create when absent --------


def test_disable_creates_file_and_dir_when_absent(project_dir: Path) -> None:
    """Disabling with no prior settings creates ``.claude/settings.json`` set off."""

    disable_native_memory(project_dir)

    path = settings_path(project_dir)
    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8")) == {SETTINGS_KEY: False}
    assert is_native_memory_enabled(project_dir) is False


def test_disable_sets_false_on_an_empty_file(project_dir: Path) -> None:
    """An empty settings file has nothing to preserve, so disabling writes cleanly."""

    _write_settings(project_dir, "")

    disable_native_memory(project_dir)

    assert json.loads(settings_path(project_dir).read_text(encoding="utf-8")) == {
        SETTINGS_KEY: False
    }


def test_disable_preserves_every_other_key(project_dir: Path) -> None:
    """Disabling keeps every unrelated setting, including nested structures."""

    original = {
        "permissions": {"allow": ["Bash(ls:*)"], "deny": []},
        "env": {"FOO": "bar"},
        "hooks": {"SessionStart": [{"command": "x"}]},
    }
    _write_settings(project_dir, json.dumps(original))

    disable_native_memory(project_dir)

    written = json.loads(settings_path(project_dir).read_text(encoding="utf-8"))
    assert written[SETTINGS_KEY] is False
    for key, value in original.items():
        assert written[key] == value


def test_disable_overwrites_an_existing_true_in_place(project_dir: Path) -> None:
    """An existing ``autoMemoryEnabled: true`` flips to false without moving, and
    the surrounding keys keep their original order."""

    _write_settings(
        project_dir,
        json.dumps({"a": 1, SETTINGS_KEY: True, "z": 2}),
    )

    disable_native_memory(project_dir)

    written = json.loads(settings_path(project_dir).read_text(encoding="utf-8"))
    assert written == {"a": 1, SETTINGS_KEY: False, "z": 2}
    assert list(written.keys()) == ["a", SETTINGS_KEY, "z"]


def test_disable_is_idempotent(project_dir: Path) -> None:
    """Disabling an already-disabled project leaves the same single-key result."""

    disable_native_memory(project_dir)
    disable_native_memory(project_dir)

    assert json.loads(settings_path(project_dir).read_text(encoding="utf-8")) == {
        SETTINGS_KEY: False
    }


def test_disable_refuses_to_clobber_malformed_settings(project_dir: Path) -> None:
    """Non-empty but unparseable settings are never overwritten: the write raises
    so real user config is never destroyed by a blind rewrite."""

    path = _write_settings(project_dir, '{ "permissions": ')
    before = path.read_bytes()

    with pytest.raises(json.JSONDecodeError):
        disable_native_memory(project_dir)

    assert path.read_bytes() == before


def test_disable_then_read_round_trips(project_dir: Path) -> None:
    """After a disable the read seam reports the project as off."""

    assert is_native_memory_enabled(project_dir) is True

    disable_native_memory(project_dir)

    assert is_native_memory_enabled(project_dir) is False
