"""Unit tests for curated writes (Stage 2): remember adds and dedups, an
over-cap write drives distillation (promoting durable entries into permanent
memory), and soft forget removes the entry and writes a tombstone that keeps the
fact gone (ADRs 0012, 0017, 0018).
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest

from mimer.bundle import concept_headlines, create_concept, list_concepts, render_profile
from mimer.curate import forget, main, redact, remember
from mimer.registry import Registry
from mimer.shortterm import parse_short_term, read_short_term
from mimer.store import ensure_store
from mimer.tombstones import is_tombstoned, load_tombstones

TODAY = date(2026, 7, 11)


def test_remember_adds_dated_entry_with_echo(
    store_root: Path, resolve_project: Callable[[Path], str], project_dir: Path
) -> None:
    """Remembering a fact adds a dated entry and echoes what happened."""

    pid = resolve_project(project_dir)

    result = remember("use sqlite-vec for the index", project_id=pid, root=store_root, today=TODAY)

    assert "remembered" in result.echo.lower()
    notes = parse_short_term(read_short_term(pid, store_root))["Notes"]
    assert len(notes) == 1
    assert notes[0].date == "2026-07-11"
    assert notes[0].text == "use sqlite-vec for the index"


def test_remember_duplicate_updates_not_duplicates(
    store_root: Path, resolve_project: Callable[[Path], str], project_dir: Path
) -> None:
    """Re-remembering an existing fact updates it rather than duplicating."""

    pid = resolve_project(project_dir)
    remember("prefer uv over pip", project_id=pid, root=store_root, today=date(2026, 7, 1))

    result = remember("prefer uv over pip", project_id=pid, root=store_root, today=TODAY)

    assert result.action == "updated"
    notes = parse_short_term(read_short_term(pid, store_root))["Notes"]
    assert len(notes) == 1
    assert notes[0].date == "2026-07-11"


def test_remember_dedup_key_delegates_to_the_matcher_normalised() -> None:
    """Remember-dedup keys off the matcher's exact ``normalised`` identity, not a
    private normalise copy (issue #53).

    Remember-dedup is deliberately exact, never fuzzy: it asks whether the user is
    re-stating the one note they are editing, where fuzzy overlap would silently
    overwrite a distinct-but-similar note. So it shares the matcher's exact-identity
    ``normalised``, delegating rather than re-implementing the collapse.
    """

    import inspect

    from mimer import curate
    from mimer.matcher import normalised

    # It yields the matcher's normalised form...
    assert curate._key("The  Deploy   KEY is set") == normalised("The  Deploy   KEY is set")
    # ...by calling it, so a future change to the shared identity cannot leave a stale
    # private copy behind. The call — not merely the word in the docstring — is what a
    # re-implemented collapse would lack.
    assert "normalised(" in inspect.getsource(curate._key)


def test_over_cap_durable_write_promotes_to_permanent(
    store_root: Path, resolve_project: Callable[[Path], str], project_dir: Path
) -> None:
    """An over-cap write drives distillation: durable entries are promoted into
    permanent Concepts and leave short-term, rather than being warned about and
    kept (ADR 0017's cap-driven promote-then-evict, issue #28)."""

    pid = resolve_project(project_dir)
    facts = (
        "the client prefers British English",
        "deployments run on Tuesdays",
        "the API rate limit is one hundred per minute",
    )
    for index, fact in enumerate(facts):
        remember(
            fact,
            project_id=pid,
            root=store_root,
            cap=3,
            durable=True,
            today=date(2026, 7, index + 1),
        )

    result = remember(
        "the staging box runs Ubuntu",
        project_id=pid,
        root=store_root,
        cap=3,
        durable=True,
        today=TODAY,
    )

    assert result.warning is None
    assert not result.aged_out
    assert len(list_concepts(store_root)) == 4
    notes = parse_short_term(read_short_term(pid, store_root))["Notes"]
    assert notes == []


def test_forget_removes_entry_and_writes_tombstone(
    store_root: Path, resolve_project: Callable[[Path], str], project_dir: Path
) -> None:
    """Soft forget removes the entry, tombstones it, and says the raw record
    stays."""

    pid = resolve_project(project_dir)
    remember("the staging password is hunter2", project_id=pid, root=store_root, today=TODAY)

    result = forget("the staging password is hunter2", project_id=pid, root=store_root, today=TODAY)

    assert result.action == "removed"
    assert "tombstone" in result.echo.lower()
    assert "untouched" in result.echo.lower()
    notes = parse_short_term(read_short_term(pid, store_root))["Notes"]
    assert notes == []
    assert is_tombstoned("the staging password is hunter2", project_id=pid, root=store_root)


def test_tombstoned_fact_stays_gone_across_reload(
    store_root: Path, resolve_project: Callable[[Path], str], project_dir: Path
) -> None:
    """A forgotten fact does not reappear in short-term memory on reload."""

    pid = resolve_project(project_dir)
    remember("drop the old cache table", project_id=pid, root=store_root, today=TODAY)
    forget("drop the old cache table", project_id=pid, root=store_root, today=TODAY)

    reloaded = read_short_term(pid, store_root)

    assert "drop the old cache table" not in reloaded
    assert len(load_tombstones(store_root)) == 1


def test_forget_removes_a_reworded_restatement(
    store_root: Path, resolve_project: Callable[[Path], str], project_dir: Path
) -> None:
    """Soft forget removes a reworded restatement, not just the exact wording (issue #18).

    forget delegates identity to the shared matcher, so a short-term entry that
    restates the forgotten fact in different words is removed too — a plain
    substring test would have left it behind.
    """

    pid = resolve_project(project_dir)
    remember("The prototype used a Redis cache.", project_id=pid, root=store_root, today=TODAY)

    result = forget(
        "We used Redis for the prototype cache", project_id=pid, root=store_root, today=TODAY
    )

    assert result.action == "removed"
    notes = parse_short_term(read_short_term(pid, store_root))["Notes"]
    assert notes == []


def test_forget_short_phrase_keeps_an_unrelated_longer_entry(
    store_root: Path, resolve_project: Callable[[Path], str], project_dir: Path
) -> None:
    """A short forget phrase must not over-remove an unrelated longer entry (issue #18).

    Substring forget removed every entry that merely contained the phrase; the
    shared matcher's specificity guard keeps a short phrase from matching a longer,
    unrelated memory.
    """

    pid = resolve_project(project_dir)
    unrelated = "The analytics pipeline uses Redis Streams to buffer events before the load."
    remember(unrelated, project_id=pid, root=store_root, today=TODAY)

    forget("uses redis", project_id=pid, root=store_root, today=TODAY)

    notes = parse_short_term(read_short_term(pid, store_root))["Notes"]
    assert any("analytics pipeline" in entry.text for entry in notes)


def test_forget_phrase_whose_words_scatter_keeps_an_unrelated_longer_entry(
    store_root: Path, resolve_project: Callable[[Path], str], project_dir: Path
) -> None:
    """A forget phrase past the guard must not over-remove an unrelated entry (issue #18).

    ``test_forget_short_phrase_keeps_an_unrelated_longer_entry`` uses a two-word
    phrase the guard rejects before the containment path runs. This phrase carries
    three content words — ``deploy``, ``window``, ``friday`` — all present in the
    unrelated entry but scattered across separate clauses, so it locks the forget
    site against over-removal on the path the guard alone does not cover.
    """

    pid = resolve_project(project_dir)
    unrelated = (
        "The office moved the deploy schedule so the testing window is wider, "
        "and the celebration happens on friday."
    )
    remember(unrelated, project_id=pid, root=store_root, today=TODAY)

    forget("deploy window friday", project_id=pid, root=store_root, today=TODAY)

    notes = parse_short_term(read_short_term(pid, store_root))["Notes"]
    assert any("celebration happens on friday" in entry.text for entry in notes)


def test_forget_retracts_a_matching_permanent_concept_across_short_term_and_injection(
    store_root: Path, resolve_project: Callable[[Path], str], project_dir: Path
) -> None:
    """A soft forget reaches permanent memory: it removes the short-term entry,
    retracts the matching pinned Concept, and stops the fact appearing in the
    injected profile and manifest headlines — the full ADR 0012 cascade (issue #32).
    """

    pid = resolve_project(project_dir)
    create_concept(
        title="Deploy day",
        body="Deployments run on Tuesdays.",
        concept_type="Reference",
        origin=pid,
        scope="project",
        pinned=True,
        confirmed=True,
        root=store_root,
    )
    remember("Deployments run on Tuesdays.", project_id=pid, root=store_root, today=TODAY)

    result = forget("Deployments run on Tuesdays.", project_id=pid, root=store_root, today=TODAY)

    assert result.action == "removed"
    assert parse_short_term(read_short_term(pid, store_root))["Notes"] == []
    assert list_concepts(store_root) == []
    assert concept_headlines(store_root, project_id=pid) == []
    assert render_profile(store_root) == ""
    assert is_tombstoned("Deployments run on Tuesdays.", project_id=pid, root=store_root)


def test_forget_retracts_a_reworded_concept_even_with_no_short_term_entry(
    store_root: Path, resolve_project: Callable[[Path], str], project_dir: Path
) -> None:
    """Forget retracts a Concept restated in different words, even when nothing in
    short-term memory matches — identity is the shared matcher, so a forget still
    reaches the permanent layer it never touched before (issue #32)."""

    pid = resolve_project(project_dir)
    create_concept(
        title="Prototype cache",
        body="The prototype used a Redis cache.",
        concept_type="Reference",
        origin=pid,
        scope="project",
        root=store_root,
    )

    result = forget(
        "We used Redis for the prototype cache", project_id=pid, root=store_root, today=TODAY
    )

    assert result.action == "tombstoned"
    assert list_concepts(store_root) == []


def test_redact_also_retracts_a_matching_permanent_concept(
    store_root: Path, resolve_project: Callable[[Path], str], project_dir: Path
) -> None:
    """Redact is a superset of forget (ADR 0012), so it too retracts a matching
    Concept — the hard tier must not leave in permanent memory what the soft tier
    would have retracted (issue #32)."""

    pid = resolve_project(project_dir)
    create_concept(
        title="Deploy day",
        body="Deployments run on Tuesdays.",
        concept_type="Reference",
        origin=pid,
        scope="project",
        root=store_root,
    )

    redact("Deployments run on Tuesdays.", project_id=pid, root=store_root, today=TODAY)

    assert list_concepts(store_root) == []


def test_forget_leaves_a_near_miss_concept_that_only_differs_by_a_value(
    store_root: Path, resolve_project: Callable[[Path], str], project_dir: Path
) -> None:
    """Forget's retraction now drives irreversible Concept deletion, so the shared
    matcher's value-substitution guard is what bounds the blast radius: a Concept
    that differs from the forgotten fact by a single value (``port 8080`` versus
    ``port 9090``) is a contradiction, not a restatement, so the deletion never
    reaches it (issue #32, ADR 0012).

    This is the near-miss the escalation from reversible suppression to irreversible
    deletion makes load-bearing — a false positive here would permanently destroy a
    distinct Concept — so it is pinned explicitly rather than left to the matcher's
    own unit tests.
    """

    pid = resolve_project(project_dir)
    create_concept(
        title="Port",
        body="The service listens on port 8080.",
        concept_type="Reference",
        origin=pid,
        scope="project",
        root=store_root,
    )

    forget("The service listens on port 9090.", project_id=pid, root=store_root, today=TODAY)

    assert [c.body for c in list_concepts(store_root)] == ["The service listens on port 8080."]


def test_forget_survives_a_concept_that_vanishes_mid_cascade(
    store_root: Path,
    resolve_project: Callable[[Path], str],
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The retraction loop lists Concepts without a lock, so a concurrent writer
    (another curate call, a supersede, a detached distiller — ADR 0011) can unlink a
    matching Concept between the list and retract_concept's own lock, making
    read_concept raise. Forget is a trust operation, so it must skip the vanished
    slug and finish the cascade — still writing the tombstone — rather than crash
    (issue #32, the invariant issue #17 established for list_concepts).
    """

    pid = resolve_project(project_dir)
    create_concept(
        title="Deploy day",
        body="Deployments run on Tuesdays.",
        concept_type="Reference",
        origin=pid,
        scope="project",
        root=store_root,
    )

    # Simulate the file vanishing in the window between the list and the lock.
    def vanished(_slug: str, _root: Path) -> None:
        raise FileNotFoundError(_slug)

    monkeypatch.setattr("mimer.curate.retract_concept", vanished)

    forget("Deployments run on Tuesdays.", project_id=pid, root=store_root, today=TODAY)

    assert is_tombstoned("Deployments run on Tuesdays.", project_id=pid, root=store_root)


def test_remembered_secret_is_stored_redacted(
    store_root: Path, resolve_project: Callable[[Path], str], project_dir: Path
) -> None:
    """A secret passed to remember is stripped before it lands in short-term memory
    (ADR-level guarantee: redaction is enforced at the sink, not by agent judgment)."""

    pid = resolve_project(project_dir)
    secret = "AKIA" + "IOSFODNN7" + "EXAMPLE"

    remember(f"the deploy key is {secret}", project_id=pid, root=store_root, today=TODAY)

    stored = read_short_term(pid, store_root)
    assert secret not in stored
    assert "REDACTED" in stored
    # Redaction removes the secret without destroying the surrounding fact.
    assert "deploy key" in stored


def test_forget_by_the_full_secret_removes_the_redacted_entry(
    store_root: Path, resolve_project: Callable[[Path], str], project_dir: Path
) -> None:
    """Forgetting by the exact secret string still removes the entry that remember
    stored in redacted form, and no raw secret is persisted to the tombstone
    ledger (forget runs the same redacting sink as remember — issue #23)."""

    pid = resolve_project(project_dir)
    secret = "AKIA" + "IOSFODNN7" + "EXAMPLE"
    remember(f"the deploy key is {secret}", project_id=pid, root=store_root, today=TODAY)

    result = forget(f"the deploy key is {secret}", project_id=pid, root=store_root, today=TODAY)

    assert result.action == "removed"
    assert parse_short_term(read_short_term(pid, store_root))["Notes"] == []
    tombstones = load_tombstones(store_root)
    assert tombstones and all(secret not in t["text"] for t in tombstones)


def test_remember_persists_for_a_new_session(
    store_root: Path, resolve_project: Callable[[Path], str], project_dir: Path
) -> None:
    """A remembered fact is present when short-term memory is read afresh (the
    automated proxy for the manual restart residue)."""

    pid = resolve_project(project_dir)
    remember("the client prefers British English", project_id=pid, root=store_root, today=TODAY)

    assert "the client prefers British English" in read_short_term(pid, store_root)


def test_cli_remember_writes_and_echoes(
    store_root: Path, resolve_project: Callable[[Path], str], project_dir: Path
) -> None:
    """The ``mimer-memory`` CLI the skill drives writes to the resolved project
    and echoes the outcome."""

    executable = Path(sys.executable).parent / "mimer-memory"
    env = {**os.environ, "MIMER_HOME": str(store_root)}
    env.pop("MIMER_GUARD", None)

    result = subprocess.run(
        [str(executable), "remember", "the CLI path works end to end"],
        cwd=str(project_dir),
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "remembered" in result.stdout.lower()
    pid = resolve_project(project_dir)
    assert "the CLI path works end to end" in read_short_term(pid, store_root)


def test_cli_note_stores_redacted(
    store_root: Path, resolve_project: Callable[[Path], str], project_dir: Path
) -> None:
    """The ``note`` CLI verb runs the same redacting sink as remember, so a secret
    noted at the command line is stored redacted (AC1 names remember and note)."""

    executable = Path(sys.executable).parent / "mimer-memory"
    env = {**os.environ, "MIMER_HOME": str(store_root)}
    env.pop("MIMER_GUARD", None)
    secret = "AKIA" + "IOSFODNN7" + "EXAMPLE"

    result = subprocess.run(
        [str(executable), "note", f"the deploy key is {secret}"],
        cwd=str(project_dir),
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    pid = resolve_project(project_dir)
    stored = read_short_term(pid, store_root)
    assert secret not in stored
    assert "deploy key" in stored


def test_curated_write_refusal_names_confirm_command_and_candidate(
    store_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A curated write refuses when identity needs confirmation, and the refusal
    names the confirm command and the candidate id so the user has a way forward,
    not just a dead end (#34)."""

    ensure_store(store_root)
    registry = Registry.load(store_root)
    registry.create("secret-client", paths=[str((tmp_path / "orig").resolve())])
    registry.save()

    clone = tmp_path / "clone"
    clone.mkdir()
    (clone / ".mimer").write_text("secret-client\n", encoding="utf-8")

    monkeypatch.setenv("MIMER_HOME", str(store_root))
    monkeypatch.chdir(clone)
    exit_code = main(["remember", "something worth keeping"])

    assert exit_code == 1
    out = capsys.readouterr().out
    assert "mimer-manage confirm secret-client" in out
    # Nothing was written: the clone acquired no short-term memory.
    assert not (tmp_path / "clone" / "short-term.md").exists()
