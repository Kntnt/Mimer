"""Tests that the memory skill exists as a real, readable prose file the agent
consults, carrying the editable judgment rules (ADR 0018).
"""

from __future__ import annotations

from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent / "skills" / "memory" / "SKILL.md"


def test_skill_file_exists_with_frontmatter() -> None:
    """The memory skill exists with name and description frontmatter."""

    assert SKILL.is_file()
    text = SKILL.read_text(encoding="utf-8")
    assert text.startswith("---")
    assert "name: memory" in text
    assert "description:" in text


def test_skill_declares_trigger_phrases() -> None:
    """The skill names its trigger phrases so the agent knows when to act."""

    text = SKILL.read_text(encoding="utf-8").lower()
    assert "remember" in text
    assert "note that" in text
    assert "forget about" in text


def test_skill_carries_forget_disambiguation_rule() -> None:
    """The judgment rules distinguish 'forget about X for now' (defer) from a
    real deletion (ADR 0018)."""

    text = SKILL.read_text(encoding="utf-8").lower()
    assert "for now" in text
    assert "defer" in text


def test_skill_invokes_the_curated_write_engine() -> None:
    """The skill drives the deterministic engine rather than hand-editing files."""

    text = SKILL.read_text(encoding="utf-8")
    assert "mimer-memory" in text
