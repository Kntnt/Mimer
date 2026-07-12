"""Tests for packaging and first run (Stage 8): the interpreter capability
check, embedding-model pre-fetch, install flow, health surfacing at session
start, and the uninstall pointer (ADR 0019).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from mimer.bundle import create_concept, list_concepts
from mimer.embedding import embed
from mimer.failure_log import fresh_failures, log_failure
from mimer.install import (
    InstallReport,
    check_sqlite_extensions,
    install_main,
    prefetch_embedding_model,
    run_install,
    write_uninstall_pointer,
)
from mimer.store import ensure_store
from tests.harness import run_hook, session_start_payload

# Every test here loads the embedding model (directly or via a hook subprocess),
# so the session fixture prefetches it once before the suite runs (conftest.py).
pytestmark = pytest.mark.embedding

README = Path(__file__).resolve().parent.parent / "README.md"


def test_sqlite_extension_check_passes_here(store_root: Path) -> None:
    """On a capable interpreter the SQLite extension check reports no problem."""

    assert check_sqlite_extensions() is None


def test_sqlite_extension_check_is_actionable_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """When extensions cannot load, the check returns an actionable message."""

    def broken(_connection: object) -> None:
        raise RuntimeError("extension loading is not supported")

    monkeypatch.setattr("mimer.install.sqlite_vec.load", broken)
    message = check_sqlite_extensions()

    assert message is not None
    assert "sqlite" in message.lower()
    assert "python" in message.lower()


def test_prefetch_embedding_model_makes_embedding_work(store_root: Path) -> None:
    """Pre-fetching the model means embedding works without a mid-session download."""

    prefetch_embedding_model()

    vector = embed(["hello world"])
    assert len(vector) == 1 and len(vector[0]) == 256


def test_run_install_creates_store_and_reports_ok(store_root: Path) -> None:
    """The install flow creates the store and reports success on a capable host."""

    report = run_install(store_root)

    assert report.ok
    assert (store_root / "mimer.log").exists()


def test_run_install_creates_the_index_so_writes_are_indexed(store_root: Path) -> None:
    """Install creates the index up front, so later capture/import writes are
    searchable without a manual reindex."""

    from mimer.capture import capture_from_payload
    from mimer.index import index_db_path, search
    from tests.transcript_fixture import write_transcript

    run_install(store_root)
    assert index_db_path(store_root).exists()

    project = store_root.parent / "proj"
    project.mkdir(exist_ok=True)
    transcript = write_transcript(
        project / "t.jsonl", [("q", "we chose ripgrep for fast search", "2026-07-11T10:00:00Z")]
    )
    capture_from_payload({"cwd": str(project), "transcript_path": str(transcript)}, root=store_root)

    assert search("what search tool did we pick", root=store_root)


def test_run_install_reports_gracefully_on_model_download_failure(
    store_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A model-download failure yields an actionable report, not a traceback."""

    def offline(_texts: list[str]) -> list[list[float]]:
        raise RuntimeError("Failed to connect to huggingface.co")

    monkeypatch.setattr("mimer.install.embed", offline)
    report = run_install(store_root)

    assert not report.ok
    assert report.messages
    joined = " ".join(report.messages).lower()
    assert "model" in joined
    assert "re-run" in joined


def test_run_install_reports_gracefully_on_index_build_failure(
    store_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An index-build failure yields an actionable report, not a traceback."""

    # Isolate the index-build path: stub the prefetch so this test reaches the
    # reindex failure deterministically, never a real model download that would
    # fail first offline and report the wrong step.
    monkeypatch.setattr("mimer.install.prefetch_embedding_model", lambda: None)

    def broken(_root: Path) -> int:
        raise RuntimeError("disk I/O error building the index")

    monkeypatch.setattr("mimer.install.reindex", broken)
    report = run_install(store_root)

    assert not report.ok
    assert report.messages
    joined = " ".join(report.messages).lower()
    assert "index" in joined
    assert "re-run" in joined


def test_run_install_resumes_after_a_pre_index_failure(
    store_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure before the index build (the model download) leaves a resumable
    state: the store survives the failure and a re-run, once the cause is fixed,
    completes cleanly. Covers the failure point that runs before reindex; the
    mid-reindex case is covered by the partial-index test below."""

    from mimer.index import index_db_path

    # First run fails at the model-download step (no network); the store is
    # created before that step, so the failure loses nothing.
    def offline(_texts: list[str]) -> list[list[float]]:
        raise RuntimeError("Failed to connect to huggingface.co")

    monkeypatch.setattr("mimer.install.embed", offline)
    first = run_install(store_root)
    assert not first.ok
    assert (store_root / "mimer.log").exists()

    # Fix the cause (network restored) and re-run the same store: the install
    # now completes and ends with a built index.
    monkeypatch.undo()
    second = run_install(store_root)
    assert second.ok
    assert index_db_path(store_root).exists()


def test_run_install_resumes_after_a_partial_index_build(store_root: Path) -> None:
    """The riskier case: a failure *during* the index build leaves a half-built
    index.db behind, and a re-run must recover from it. reindex drops any existing
    index before rebuilding, so the re-run produces a complete, searchable index —
    the mid-reindex half of run_install's resumability promise."""

    from mimer.index import index_db_path, search

    # Seed indexable content so the index build has real work — and thus a real
    # embed call — to fail on.
    create_concept(
        title="Search tool choice",
        body="we chose ripgrep for fast search",
        concept_type="Fact",
        origin="p",
        scope="global",
        root=store_root,
    )

    # First run: the model download is stubbed out so the build is reached
    # deterministically, then the index build fails partway — after reindex has
    # already created the index.db file, the half-built artifact to recover from.
    with pytest.MonkeyPatch.context() as first_run:
        first_run.setattr("mimer.install.prefetch_embedding_model", lambda: None)

        def broken(_texts: list[str]) -> list[list[float]]:
            raise RuntimeError("disk I/O error building the index")

        first_run.setattr("mimer.index.embed", broken)
        first = run_install(store_root)
    assert not first.ok
    assert index_db_path(store_root).exists()

    # Second run: with the cause fixed, the re-run drops the half-built index and
    # rebuilds a complete one that answers a query about the seeded content.
    with pytest.MonkeyPatch.context() as second_run:
        second_run.setattr("mimer.install.prefetch_embedding_model", lambda: None)
        second = run_install(store_root)
    assert second.ok
    assert search("what search tool did we pick", root=store_root)


def test_install_main_reports_a_failure_as_exit_code_one(
    store_root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The install entry point degrades a failing report to exit code 1 with the
    actionable message printed — never a propagated traceback."""

    monkeypatch.setattr("mimer.install.store_root", lambda: store_root)
    monkeypatch.setattr(
        "mimer.install.run_install",
        lambda _root: InstallReport(False, ["could not fetch the embedding model — re-run"]),
    )

    code = install_main()
    output = capsys.readouterr().out

    assert code == 1
    assert "could not fetch the embedding model" in output


def test_install_main_reports_success_as_exit_code_zero(
    store_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A successful report maps to exit code 0."""

    monkeypatch.setattr("mimer.install.store_root", lambda: store_root)
    monkeypatch.setattr(
        "mimer.install.run_install", lambda _root: InstallReport(True, ["store ready"])
    )

    assert install_main() == 0


def test_fresh_failures_are_recent_only(store_root: Path) -> None:
    """Only recently-logged failures count as fresh."""

    ensure_store(store_root)
    old = (datetime.now(UTC) - timedelta(days=3)).isoformat()
    (store_root / "mimer.log").write_text(f"{old}\tan old failure\n", encoding="utf-8")
    log_failure("a brand new failure", root=store_root)

    fresh = fresh_failures(store_root)

    assert any("brand new" in line for line in fresh)
    assert all("old failure" not in line for line in fresh)


def test_fresh_failures_surface_at_session_start(store_root: Path, project_dir: Path) -> None:
    """A fresh failure surfaces as a one-line health notice at session start."""

    ensure_store(store_root)
    log_failure("capture could not reach the transcript", root=store_root)

    result = run_hook(
        "SessionStart",
        session_start_payload(cwd=str(project_dir)),
        store_root=store_root,
        cwd=project_dir,
    )

    context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "health" in context.lower() or "failure" in context.lower()


def test_uninstall_writes_pointer_and_keeps_the_store(store_root: Path) -> None:
    """Uninstall leaves the store in place with a pointer note."""

    ensure_store(store_root)
    create_concept(
        title="Kept knowledge",
        body="This should survive uninstall.",
        concept_type="Fact",
        origin="p",
        scope="global",
        root=store_root,
    )

    pointer = write_uninstall_pointer(store_root)

    assert pointer.exists()
    assert "mimer" in pointer.read_text(encoding="utf-8").lower()
    assert list_concepts(store_root), "the store must be left intact"


def test_readme_documents_install_and_coexistence() -> None:
    """The README documents installation and native-memory coexistence."""

    text = README.read_text(encoding="utf-8")
    assert "## Installation" in text
    assert "plugin" in text.lower()
    assert "autoMemoryEnabled" in text
