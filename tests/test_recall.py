"""Tests for recall core (Stage 4a): a hybrid sqlite-vec + FTS5 index over
long-term memory, cited search reranked and tombstone-filtered, and a reindex
that rebuilds the derived index reproducibly (ADRs 0007, 0011, 0012).
"""

from __future__ import annotations

from pathlib import Path

from mimer.capture import capture_from_payload
from mimer.index import index_db_path, reindex, search
from mimer.longterm import daily_log_path
from mimer.tombstones import write_tombstone
from tests.transcript_fixture import write_transcript

PID = "proj-a"


def _seed(store_root: Path, date_str: str, blocks: list[tuple[str, str]]) -> None:
    """Write a daily long-term log with the given heading/body blocks."""

    path = daily_log_path(PID, date_str, store_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(f"## {h}\n\n{b}\n" for h, b in blocks), encoding="utf-8")


def _seed_corpus(store_root: Path) -> None:
    _seed(
        store_root,
        "2026-06-01",
        [
            ("Release cadence", "The team agreed to deploy new releases on Fridays after standup."),
            ("Billing", "The invoice for the monthly cloud bill is due next Tuesday."),
            ("Auth rework", "We refactored the login system to use JWT access tokens."),
        ],
    )


def test_paraphrased_query_hits_and_cites(store_root: Path) -> None:
    """A paraphrased query finds the right entry and cites it fully."""

    _seed_corpus(store_root)
    reindex(store_root)

    results = search("when do we ship new versions?", root=store_root, project_id=PID)

    assert results, "expected a hit for a paraphrased query"
    top = results[0]
    assert "Fridays" in top.text
    assert top.date == "2026-06-01"
    assert top.heading == "Release cadence"
    assert top.source.endswith("2026-06-01.md")
    assert top.excerpt


def test_keyword_and_meaning_both_surface(store_root: Path) -> None:
    """A keyword-only match and a meaning-only match both surface (hybrid)."""

    _seed(
        store_root,
        "2026-06-02",
        [
            ("Feature flag", "The config flag is named ENABLE_TURBO_MODE in settings."),
            ("Onboarding", "New hires get their laptops on the first morning."),
        ],
    )
    reindex(store_root)

    keyword = search("ENABLE_TURBO_MODE", root=store_root, project_id=PID)
    meaning = search("what do employees receive when they start?", root=store_root, project_id=PID)

    assert any("ENABLE_TURBO_MODE" in r.text for r in keyword)
    assert any("laptops" in r.text for r in meaning)


def test_tombstoned_fact_does_not_surface(store_root: Path) -> None:
    """A tombstoned fact is filtered out of recall."""

    fact = "The legacy endpoint /v1/old will be removed in the next release."
    _seed(store_root, "2026-06-03", [("Cleanup", fact)])
    reindex(store_root)
    assert search("what is happening to the legacy endpoint?", root=store_root, project_id=PID)

    write_tombstone(fact, project_id=PID, root=store_root)

    results = search("what is happening to the legacy endpoint?", root=store_root, project_id=PID)
    assert all("/v1/old" not in r.text for r in results)


def test_short_tombstone_does_not_suppress_an_unrelated_longer_memory(store_root: Path) -> None:
    """A short tombstone must not hide a longer, unrelated memory (issue #18).

    Recall suppressed anything whose text merely contained the tombstone as a
    substring, so tombstoning a short phrase silently hid unrelated memories. The
    shared matcher, keyed on whole-fact overlap, no longer over-suppresses.
    """

    unrelated = "The analytics pipeline uses Redis Streams to buffer events before the load."
    _seed(store_root, "2026-06-04", [("Analytics", unrelated)])
    reindex(store_root)
    assert search("how does the analytics pipeline buffer events?", root=store_root, project_id=PID)

    write_tombstone("uses redis", project_id=PID, root=store_root)

    results = search(
        "how does the analytics pipeline buffer events?", root=store_root, project_id=PID
    )
    assert any("analytics pipeline" in r.text for r in results)


def test_tombstoned_fact_in_a_multi_fact_capture_chunk_is_suppressed(store_root: Path) -> None:
    """A forgotten fact bundled with others in one chunk is still suppressed (issue #18).

    A captured turn packs a whole User+Assistant exchange under one heading, so a
    chunk is routinely far larger than any single fact it contains. Recall must
    still suppress a chunk that carries a forgotten fact, or the fact resurfaces
    verbatim in that chunk and the forget is defeated (ADR 0012).
    """

    secret = "the staging password is hunter2"
    body = (
        f"- Assistant: session tokens live in Redis, the cache warms on boot, and {secret} "
        "until the next rotation.\n"
        "- User: how do we handle secrets in staging?"
    )
    _seed(store_root, "2026-06-05", [("Turn digest", body)])
    reindex(store_root)
    assert search("what is the staging password?", root=store_root, project_id=PID)

    write_tombstone(secret, project_id=PID, root=store_root)

    results = search("what is the staging password?", root=store_root, project_id=PID)
    assert all("hunter2" not in r.text for r in results)


def test_tombstoned_fact_in_an_aged_out_block_is_suppressed(store_root: Path) -> None:
    """A forgotten fact inside an aged-out block is suppressed (issue #18).

    Aged-out blocks group many facts under one heading, so the chunk dwarfs the
    single forgotten fact — the same multi-fact regression as a captured turn.
    """

    secret = "the api key is sk-live-42"
    body = (
        "- [2026-06-05] the deploy window is friday afternoon\n"
        f"- [2026-06-05] {secret}\n"
        "- [2026-06-05] the oncall rotation is weekly"
    )
    _seed(store_root, "2026-06-06", [("Aged out of short-term (2026-06-06)", body)])
    reindex(store_root)
    assert search("what is the api key?", root=store_root, project_id=PID)

    write_tombstone(secret, project_id=PID, root=store_root)

    results = search("what is the api key?", root=store_root, project_id=PID)
    assert all("sk-live-42" not in r.text for r in results)


def test_unanswerable_query_returns_empty(store_root: Path) -> None:
    """A query unrelated to anything stored returns an explicit empty result."""

    _seed_corpus(store_root)
    reindex(store_root)

    results = search(
        "photosynthesis in tropical orchids during monsoon season",
        root=store_root,
        project_id=PID,
    )

    assert results == []


def test_reindex_reproduces_identical_results(store_root: Path) -> None:
    """Deleting the index and reindexing reproduces identical search results."""

    _seed_corpus(store_root)
    reindex(store_root)
    query = "how does authentication work now?"
    before = [(r.heading, r.excerpt) for r in search(query, root=store_root, project_id=PID)]

    index_db_path(store_root).unlink()
    reindex(store_root)
    after = [(r.heading, r.excerpt) for r in search(query, root=store_root, project_id=PID)]

    assert before == after
    assert before, "expected non-empty results to compare"


def test_capture_write_appears_in_search(store_root: Path, project_dir: Path) -> None:
    """A captured turn is searchable without any manual indexing step."""

    # Build the index so incremental indexing is active.
    reindex(store_root)
    transcript = write_transcript(
        project_dir / "t.jsonl",
        [
            (
                "how do we cache?",
                "we memoise results in a per-run dictionary",
                "2026-07-11T10:00:00Z",
            )
        ],
    )

    capture_from_payload(
        {"cwd": str(project_dir), "transcript_path": str(transcript)}, root=store_root
    )

    results = search("what is the caching strategy?", root=store_root)
    assert any("memoise" in r.text for r in results)
