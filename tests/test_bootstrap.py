"""Tests for bootstrap (Stage 7): a per-project, resumable import of pre-existing
Claude Code history into memory, finishing with a distillation pass — excluding
Mimer-spawned sessions and degrading gracefully on an unknown format (ADR 0009).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mimer.bootstrap import bootstrap_project
from mimer.bundle import list_concepts, profile_concepts
from mimer.index import reindex, search
from mimer.longterm import daily_log_path
from mimer.project import resolve
from mimer.shortterm import read_short_term
from mimer.store import ensure_store
from tests.transcript_fixture import write_transcript

MIMER_DIGEST_PROMPT = "You are Mimer's session digester. Summarise the following coding session."


def _project(store_root: Path, cwd: Path) -> str:
    resolution = resolve(cwd, root=store_root)
    assert resolution.project_id is not None
    return resolution.project_id


def _all_logs(store_root: Path, pid: str) -> str:
    directory = daily_log_path(pid, "2000-01-01", store_root).parent
    if not directory.exists():
        return ""
    return "".join(log.read_text() for log in directory.glob("*.md"))


def test_import_once_then_rerun_adds_nothing(store_root: Path, project_dir: Path) -> None:
    """A fixture history imports once; re-running a completed import adds nothing."""

    pid = _project(store_root, project_dir)
    source = project_dir / "history"
    write_transcript(source / "a.jsonl", [("q1", "answer one", "2026-06-01T10:00:00Z")])
    write_transcript(source / "b.jsonl", [("q2", "answer two", "2026-06-02T10:00:00Z")])

    first = bootstrap_project(pid, transcripts_dir=source, root=store_root)
    second = bootstrap_project(pid, transcripts_dir=source, root=store_root)

    assert first.imported_turns == 2
    assert second.imported_turns == 0
    assert _all_logs(store_root, pid).count("answer one") == 1


def test_crash_mid_import_resumes(
    store_root: Path, project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A crash mid-import resumes rather than restarting."""

    pid = _project(store_root, project_dir)
    source = project_dir / "history"
    write_transcript(
        source / "a.jsonl", [("q1", "first transcript answer", "2026-06-01T10:00:00Z")]
    )
    write_transcript(source / "b.jsonl", [("q2", "TWOMARKER answer", "2026-06-02T10:00:00Z")])

    from mimer.longterm import append_entry as real_append

    def flaky(project_id: str, day: str, entry: str, root: Path | None = None) -> None:
        if "TWOMARKER" in entry:
            raise RuntimeError("simulated crash")
        real_append(project_id, day, entry, root)

    monkeypatch.setattr("mimer.bootstrap.append_entry", flaky)
    with pytest.raises(RuntimeError):
        bootstrap_project(pid, transcripts_dir=source, root=store_root)

    monkeypatch.undo()
    bootstrap_project(pid, transcripts_dir=source, root=store_root)

    logs = _all_logs(store_root, pid)
    assert logs.count("first transcript answer") == 1
    assert "TWOMARKER answer" in logs


def test_imported_conversation_is_recalled_and_cited(store_root: Path, project_dir: Path) -> None:
    """A query about an imported pre-install conversation returns a cited result."""

    pid = _project(store_root, project_dir)
    source = project_dir / "history"
    write_transcript(
        source / "a.jsonl",
        [("how to cache?", "we memoise with an lru_cache decorator", "2026-06-01T10:00:00Z")],
    )

    bootstrap_project(pid, transcripts_dir=source, root=store_root)
    reindex(store_root)

    hits = search("caching approach", root=store_root, project_id=pid)
    assert any("memoise" in c.text for c in hits)
    assert hits[0].source.endswith(".md")


def test_finishing_pass_yields_concepts_profile_and_short_term(
    store_root: Path, project_dir: Path
) -> None:
    """The finishing distillation yields Concepts, a starter profile and an
    initial short-term working set, redaction- and scope-compliant."""

    pid = _project(store_root, project_dir)
    source = project_dir / "history"
    secret = "AKIA" + "IOSFODNN7" + "EXAMPLE"
    write_transcript(
        source / "a.jsonl",
        [(f"key {secret}", "we adopted uv and British English", "2026-06-01T10:00:00Z")],
    )

    def distiller(_text: str) -> list[str]:
        return ["The user prefers British English.", "The project standardised on uv."]

    bootstrap_project(pid, transcripts_dir=source, root=store_root, distiller=distiller)

    assert list_concepts(store_root)
    assert profile_concepts(store_root)
    assert read_short_term(pid, store_root).strip() != ""
    # Redaction held across the import and finishing pass.
    assert secret not in _all_logs(store_root, pid)
    assert all(secret not in c.body for c in list_concepts(store_root))


def test_per_project_import_state_is_independent(store_root: Path, tmp_path: Path) -> None:
    """A project bootstrapped after another imports its own history."""

    ensure_store(store_root)
    dir_a, dir_b = tmp_path / "a", tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    pid_a, pid_b = _project(store_root, dir_a), _project(store_root, dir_b)
    write_transcript(dir_a / "h" / "a.jsonl", [("qa", "alpha history", "2026-06-01T10:00:00Z")])
    write_transcript(dir_b / "h" / "b.jsonl", [("qb", "beta history", "2026-06-02T10:00:00Z")])

    bootstrap_project(pid_a, transcripts_dir=dir_a / "h", root=store_root)
    result_b = bootstrap_project(pid_b, transcripts_dir=dir_b / "h", root=store_root)

    assert result_b.imported_turns == 1
    assert "beta history" in _all_logs(store_root, pid_b)


def test_mimer_spawned_transcripts_are_excluded(store_root: Path, project_dir: Path) -> None:
    """Mimer-spawned session transcripts are excluded from bootstrap."""

    pid = _project(store_root, project_dir)
    source = project_dir / "history"
    write_transcript(
        source / "spawned.jsonl", [(MIMER_DIGEST_PROMPT, "a digest reply", "2026-06-01T10:00:00Z")]
    )

    result = bootstrap_project(pid, transcripts_dir=source, root=store_root)

    assert result.imported_turns == 0
    assert "a digest reply" not in _all_logs(store_root, pid)


def test_finishing_distillation_zero_concepts_is_logged(
    store_root: Path, project_dir: Path
) -> None:
    """A finishing pass that yields no concepts is logged, not silent."""

    pid = _project(store_root, project_dir)
    source = project_dir / "history"
    write_transcript(source / "a.jsonl", [("q", "some durable content", "2026-06-01T10:00:00Z")])

    result = bootstrap_project(
        pid, transcripts_dir=source, root=store_root, distiller=lambda _t: []
    )

    assert result.concept_count == 0
    log = (store_root / "mimer.log").read_text().lower()
    assert "distill" in log and "no concept" in log


def test_finishing_distillation_is_retryable(store_root: Path, project_dir: Path) -> None:
    """A finishing pass that yielded nothing retries on a later run over the
    already-imported record (not blocked by the completed transcript import)."""

    pid = _project(store_root, project_dir)
    source = project_dir / "history"
    write_transcript(
        source / "a.jsonl", [("q", "durable content about uv", "2026-06-01T10:00:00Z")]
    )

    bootstrap_project(pid, transcripts_dir=source, root=store_root, distiller=lambda _t: [])
    assert not list_concepts(store_root)

    bootstrap_project(
        pid, transcripts_dir=source, root=store_root, distiller=lambda _t: ["The project uses uv."]
    )
    assert any("uv" in c.body for c in list_concepts(store_root))


def test_haiku_distiller_extracts_bullets_despite_preamble(monkeypatch: pytest.MonkeyPatch) -> None:
    """The distiller extracts the bullet list even when the model adds prose."""

    from mimer.bootstrap import _haiku_distiller

    reply = (
        "Sure! Here are the facts:\n"
        "- The user prefers uv.\n"
        "- Deploys happen on Fridays.\n"
        "Hope that helps."
    )
    monkeypatch.setattr("mimer.bootstrap.run_haiku", lambda _p: reply)

    assert _haiku_distiller("history") == ["The user prefers uv.", "Deploys happen on Fridays."]


def test_haiku_distiller_handles_none_and_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """A '- none' reply or an unavailable model yields no facts."""

    from mimer.bootstrap import _haiku_distiller

    monkeypatch.setattr("mimer.bootstrap.run_haiku", lambda _p: "- none")
    assert _haiku_distiller("history") == []

    monkeypatch.setattr("mimer.bootstrap.run_haiku", lambda _p: None)
    assert _haiku_distiller("history") == []


def test_unknown_transcript_format_degrades_gracefully(store_root: Path, project_dir: Path) -> None:
    """An unrecognised transcript format degrades with a logged, actionable message."""

    pid = _project(store_root, project_dir)
    source = project_dir / "history"
    source.mkdir(parents=True)
    (source / "garbage.jsonl").write_text("this is not a transcript at all\n", encoding="utf-8")

    result = bootstrap_project(pid, transcripts_dir=source, root=store_root)

    assert result.imported_turns == 0
    log = (store_root / "mimer.log").read_text().lower()
    assert "unrecognised" in log or "unrecognized" in log
