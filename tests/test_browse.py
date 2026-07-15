"""Tests for the read-only interactive CLI browser (``mimer-browse``, ADR 0028).

The browser reads the whole store from the terminal without starting a session.
Two seams are exercised here, both headlessly:

* the search core (:func:`mimer.browse.browse_search`) — the same hybrid index
  recall uses, but *unfiltered by scope*, so a foreign project-scoped Concept
  recall hides is visible here (the audit surface for what has become global);
* the interactive layer (:class:`mimer.browse.BrowseSession`) — a curses-free
  state machine: arrow keys move the selection, Enter opens a hit with its
  source and date, q quits. The curses driver is a thin adapter over it, so the
  behaviour is tested without a terminal.

The browser is strictly read-only (ADR 0028): no forget, no redact, no write.
:func:`test_browse_performs_no_writes_against_a_read_only_store` proves it by
snapshotting the store's memory files around a browse.
"""

from __future__ import annotations

import curses
import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from mimer import browse
from mimer.browse import BrowseSession, browse_search
from mimer.bundle import create_concept
from mimer.index import Citation, reindex
from mimer.longterm import daily_log_path
from mimer.recall import recall
from mimer.registry import Registry
from mimer.store import ensure_store
from mimer.tombstones import tombstones_path

# The keypress a real terminal sends for Return; the session also accepts
# curses.KEY_ENTER, but a raw newline is what getch() yields in practice.
_ENTER = ord("\n")


def _hit(
    token: str,
    *,
    source: str = "long-term/2026-06-01.md",
    date: str = "2026-06-01",
    heading: str = "Note",
    text: str | None = None,
) -> Citation:
    """A hand-built citation carrying ``token`` in its text, for the curses-free
    session tests (no store, no index, no embedding model)."""

    body = text if text is not None else f"{heading}\n\n{token} body about {token}."
    return Citation(
        project_id="alpha",
        source=source,
        date=date,
        heading=heading,
        excerpt=token,
        text=body,
        score=1.0,
    )


def _seed(store_root: Path, pid: str, fact: str, day: str = "2026-06-01") -> None:
    """Write a one-block daily long-term log for a project."""

    path = daily_log_path(pid, day, store_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"## Note\n\n{fact}\n", encoding="utf-8")


def _register(store_root: Path, *pids: str) -> Registry:
    """Register the named projects so the store knows of them."""

    ensure_store(store_root)
    registry = Registry.load(store_root)
    for pid in pids:
        registry.create(pid, paths=[f"/work/{pid}"])
    registry.save()
    return registry


def _memory_snapshot(root: Path) -> dict[str, str]:
    """A content hash of every store file *except* the derived index.

    The index (``index.db`` and its WAL sidecars) is derived state a pure read
    may legitimately checkpoint, so it is excluded. What remains — the daily
    logs, the permanent bundle, the registry, tombstones, the failure log — is
    the memory the browser must never touch (no forget, no redact, ADR 0028).
    """

    derived = {"index.db", "index.db-wal", "index.db-shm"}
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name not in derived
    }


# --- The interactive layer: a curses-free state machine ---------------------


def test_arrow_keys_move_the_selection_within_bounds() -> None:
    """Down moves to the next hit, up to the previous, and both clamp at the
    ends — the arrow-key navigation of acceptance criterion 2."""

    hits = [_hit("a"), _hit("b"), _hit("c")]
    session = BrowseSession("q", hits, height=24, width=80)

    assert session.selection is hits[0]
    assert session.handle_key(curses.KEY_UP) is True
    assert session.selection is hits[0]
    session.handle_key(curses.KEY_DOWN)
    assert session.selection is hits[1]
    session.handle_key(curses.KEY_DOWN)
    session.handle_key(curses.KEY_DOWN)
    assert session.selection is hits[2]


def test_enter_opens_the_selected_hit_showing_its_source_and_date() -> None:
    """Enter opens the highlighted hit, and the reading view renders it with its
    source and date (acceptance criterion 2)."""

    hits = [
        _hit("first"),
        _hit("second", source="long-term/2026-06-02.md", date="2026-06-02"),
    ]
    session = BrowseSession("q", hits)
    session.handle_key(curses.KEY_DOWN)

    keep_running = session.handle_key(_ENTER)

    assert keep_running is True
    assert session.mode == "reading"
    assert session.opened is hits[1]
    screen = "\n".join(session.render())
    assert "long-term/2026-06-02.md" in screen
    assert "2026-06-02" in screen
    assert "second" in screen


def test_q_quits_from_the_list() -> None:
    """q at the hit list ends the browser: handle_key returns False so the curses
    loop breaks (acceptance criterion 2)."""

    session = BrowseSession("q", [_hit("a")])

    assert session.handle_key(ord("q")) is False


def test_q_returns_from_a_hit_to_the_list() -> None:
    """q while reading a hit closes it back to the list rather than ending the
    browser, so the user can pick another hit."""

    session = BrowseSession("q", [_hit("a"), _hit("b")])
    session.handle_key(_ENTER)
    assert session.mode == "reading"

    keep_running = session.handle_key(ord("q"))

    assert keep_running is True
    assert session.mode == "list"


def test_reading_view_paginates_long_text_vertically() -> None:
    """A hit longer than the viewport is paginated: scrolling down reveals lines
    that were off-screen and scrolls the first ones away (the 'paginated text'
    of ADR 0028)."""

    body = "Heading\n" + "\n".join(f"line-{i:02d}" for i in range(50))
    session = BrowseSession("q", [_hit("x", text=body)], height=8, width=80)
    session.handle_key(_ENTER)

    top = "\n".join(session.render())
    for _ in range(200):
        session.handle_key(curses.KEY_DOWN)
    bottom = "\n".join(session.render())

    assert "line-00" in top and "line-49" not in top
    assert "line-49" in bottom and "line-00" not in bottom


def test_main_reports_nothing_found_without_launching_curses(
    store_root: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With nothing to show, ``main`` prints an honest empty message and exits 0
    without ever entering curses — so the command is safe to run headlessly."""

    monkeypatch.setenv("MIMER_HOME", str(store_root))
    monkeypatch.setattr(
        browse.curses, "wrapper", lambda *a, **k: pytest.fail("curses must not launch when empty")
    )

    code = browse.main(["nothing", "is", "indexed"])

    assert code == 0
    assert "nothing" in capsys.readouterr().out.lower()


# --- The search core: same index as recall, unfiltered by scope -------------


@pytest.mark.embedding
def test_browse_search_reads_across_every_scope_unlike_recall(store_root: Path) -> None:
    """The browser sees a foreign project-scoped Concept that recall — even
    widened — hides, because it does not apply recall's scope filter (acceptance
    criterion 1; ADR 0028's audit surface for what has become global).

    Recall from client-b widened across projects must never surface client-a's
    project-scoped Concept (the ADR 0013 invariant), yet the very same query
    through the browser must, so the user can audit with their own eyes what a
    project keeps.
    """

    _register(store_root, "client-a", "client-b")
    create_concept(
        title="Client A secret rule",
        body="Client A's private API base path is internal-only and confidential.",
        concept_type="Decision",
        origin="client-a",
        scope="project",
        root=store_root,
    )
    _seed(store_root, "client-a", "Client A rolled out the private API base path last sprint.")
    reindex(store_root)

    query = "client A private API base path internal-only"
    widened = recall(query, root=store_root, project_id="client-b", widen=True)
    browsed = browse_search(query, root=store_root)

    assert all("internal-only" not in citation.text for citation in widened.citations)
    assert any("internal-only" in hit.text for hit in browsed)


@pytest.mark.embedding
def test_browse_search_returns_the_hits_recall_returns(store_root: Path) -> None:
    """Where recall finds a hit, the browser finds it too: the browser is recall's
    hits widened by lifting the scope filter, never a different search — so every
    scoped hit is a subset of the unfiltered browse hits (acceptance criterion 1)."""

    _register(store_root, "alpha")
    _seed(store_root, "alpha", "deployment uses blue-green swaps in project alpha")
    reindex(store_root)

    query = "how is deployment done?"
    recalled = recall(query, root=store_root, project_id="alpha")
    browsed = browse_search(query, root=store_root)

    assert recalled.citations
    assert any("blue-green" in hit.text for hit in browsed)
    assert {citation.text for citation in recalled.citations} <= {hit.text for hit in browsed}


@pytest.mark.embedding
def test_browse_search_is_honestly_empty_for_an_unanswerable_query(store_root: Path) -> None:
    """A query unrelated to anything stored returns nothing rather than a poor
    guess — recall's honest emptiness is preserved through the browser."""

    _register(store_root, "alpha")
    _seed(store_root, "alpha", "the deployment uses blue-green swaps")
    reindex(store_root)

    assert browse_search("photosynthesis in tropical orchids", root=store_root) == []


@pytest.mark.embedding
def test_browse_performs_no_writes_against_a_read_only_store(store_root: Path) -> None:
    """Searching and opening a hit changes no memory file and creates no tombstone:
    the browser is strictly read-only — no forget, no redact (acceptance criterion 3)."""

    _register(store_root, "client-a", "client-b")
    create_concept(
        title="Client A secret rule",
        body="Client A's private API base path is internal-only and confidential.",
        concept_type="Decision",
        origin="client-a",
        scope="project",
        root=store_root,
    )
    _seed(store_root, "client-a", "Client A rolled out the private API base path last sprint.")
    reindex(store_root)

    before = _memory_snapshot(store_root)
    hits = browse_search("private API base path", root=store_root)
    assert hits, "need a hit to open"
    session = BrowseSession("private API base path", hits)
    session.handle_key(_ENTER)
    _ = "\n".join(session.render())
    after = _memory_snapshot(store_root)

    assert before == after
    assert not tombstones_path(store_root).exists()


# --- The packaged command ---------------------------------------------------


def test_browse_is_a_packaged_command_that_reports_empty_headlessly(
    store_root: Path, project_dir: Path
) -> None:
    """``mimer-browse`` is a real packaged console script: run against an empty
    store it prints an honest empty message and exits 0, never opening curses —
    exercising the packaged entry point end to end without a terminal
    (acceptance criterion 4)."""

    executable = Path(sys.executable).parent / "mimer-browse"
    env = {**os.environ, "MIMER_HOME": str(store_root)}
    env.pop("MIMER_GUARD", None)

    result = subprocess.run(
        [str(executable), "anything", "at", "all"],
        cwd=str(project_dir),
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "nothing" in result.stdout.lower()
