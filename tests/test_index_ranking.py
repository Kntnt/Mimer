"""Direct unit tests for the recall ranking internals (issues #58, #62): the
private helpers ``_fuse`` and ``_recency_factor`` the hybrid index reranks with,
and the reranker ``_cite`` that folds them into a cited, recency-ranked score.

The reranker no longer weights an entry by its heading: the former "session
digest" / "aged out" source weight is gone (ADR 0023, issue #62), so ``_cite``
ranks by the fused match and recency alone.

These are *characterisation* tests: they read the current implementation and pin
its actual properties at an internal seam of the indexer, so a later retuning of
a weight constant or the fusion maths becomes a deliberate red-then-edit rather
than a silent drift surfacing (if at all) as a distant full-``search`` assertion
far from the code that promised the behaviour. The module's public interface
stays ``search``; a module may keep internal seams its own tests exercise.

The helpers here take plain values, so — unlike the recall suites that drive full
``search`` calls — these tests need no store, no on-disk ``index.db`` and no
embedding model, and therefore carry no ``embedding`` marker. ``_fuse`` does read
from a connection, so it runs against a throwaway in-memory SQLite database whose
two virtual tables are populated by hand and whose query embedding is stubbed;
the real model is never loaded.
"""

from __future__ import annotations

import math
import sqlite3
from datetime import date

import pytest
import sqlite_vec

from mimer import index
from mimer.embedding import EMBEDDING_DIMENSIONS

# Width of an index vector — the same constant the real schema is built with, so
# a hand-made vector always matches ``vec_chunks``.
DIM = EMBEDDING_DIMENSIONS


def _unit(vector: list[float]) -> list[float]:
    """Normalise a vector to unit length, as ``embed`` does, so a plain L2
    distance in the index reads back as cosine similarity."""

    norm = math.sqrt(sum(component * component for component in vector)) or 1.0
    return [component / norm for component in vector]


def _dense(*axes: tuple[int, float]) -> list[float]:
    """A unit ``DIM``-vector with the given (index, weight) components set and the
    rest zero — enough to place a chunk at a chosen cosine to the query."""

    vector = [0.0] * DIM
    for position, weight in axes:
        vector[position] = weight
    return _unit(vector)


def _memory_index() -> sqlite3.Connection:
    """A throwaway in-memory index: sqlite-vec loaded and the real schema, but no
    store and no ``index.db`` file. ``_fuse`` reads only ``vec_chunks`` and
    ``chunks_fts``, which each test fills by hand."""

    connection = sqlite3.connect(":memory:")
    connection.enable_load_extension(True)
    sqlite_vec.load(connection)
    connection.enable_load_extension(False)
    index._ensure_schema(connection)
    return connection


def _add_vector(connection: sqlite3.Connection, rowid: int, vector: list[float]) -> None:
    """Place a chunk into the vector list at a chosen embedding."""

    connection.execute(
        "INSERT INTO vec_chunks(rowid, embedding) VALUES (?, ?)",
        (rowid, sqlite_vec.serialize_float32(vector)),
    )


def _add_keyword(connection: sqlite3.Connection, rowid: int, text: str) -> None:
    """Place a chunk into the keyword list with the given searchable text."""

    connection.execute("INSERT INTO chunks_fts(rowid, text) VALUES (?, ?)", (rowid, text))


def _stub_query_embedding(monkeypatch: pytest.MonkeyPatch, vector: list[float]) -> None:
    """Make ``_fuse`` embed its query to ``vector`` without loading the model."""

    monkeypatch.setattr(index, "embed", lambda texts: [vector])


# Distinct rowids so a mix-up between the three roles is obvious in a failure.
_BOTH = 1
_KEYWORD_ONLY = 2
_VECTOR_ONLY = 3


def _hybrid_index(monkeypatch: pytest.MonkeyPatch) -> sqlite3.Connection:
    """A three-chunk index: one chunk in both lists, one vector-only and one
    keyword-only, with the query stubbed to embed onto the ``_BOTH`` chunk.

    ``_BOTH`` sits on the query (cosine 1.0) and carries both query words;
    ``_VECTOR_ONLY`` is near the query (cosine 0.5) but wordless; ``_KEYWORD_ONLY``
    carries a query word but is absent from the vector index.
    """

    connection = _memory_index()
    _add_vector(connection, _BOTH, _dense((0, 1.0)))
    _add_vector(connection, _VECTOR_ONLY, _dense((0, 0.5), (1, math.sqrt(0.75))))
    _add_keyword(connection, _BOTH, "alpha beta gamma")
    _add_keyword(connection, _KEYWORD_ONLY, "alpha delta")
    _stub_query_embedding(monkeypatch, _dense((0, 1.0)))
    return connection


def test_fuse_ranks_an_item_in_both_lists_above_an_item_in_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A chunk both searches return outranks a chunk only one returns: reciprocal
    -rank fusion sums the two contributions, so being found twice beats being
    found once."""

    connection = _hybrid_index(monkeypatch)

    scores = index._fuse(connection, "alpha beta")

    assert scores[_BOTH] > scores[_KEYWORD_ONLY]
    assert scores[_BOTH] > scores[_VECTOR_ONLY]


def test_fuse_surfaces_an_item_present_in_only_one_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hit found by only the vector search, or only the keyword search, still
    reaches the fused candidate set — hybrid recall never drops a one-sided
    match."""

    connection = _hybrid_index(monkeypatch)

    scores = index._fuse(connection, "alpha beta")

    assert _VECTOR_ONLY in scores
    assert _KEYWORD_ONLY in scores


def test_fuse_sums_reciprocal_ranks_with_the_tuned_offset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A lone chunk ranked 0 in both lists scores 1/(60+0) + 1/(60+0): the
    reciprocal-rank offset is 60 and the two lists' contributions are summed.
    The expected 2/60 is hard-coded (not read from ``_RRF_K``), so a change to
    the offset or a switch away from summation fails here."""

    connection = _memory_index()
    _add_vector(connection, _BOTH, _dense((0, 1.0)))
    _add_keyword(connection, _BOTH, "alpha")
    _stub_query_embedding(monkeypatch, _dense((0, 1.0)))

    scores = index._fuse(connection, "alpha")

    assert set(scores) == {_BOTH}
    assert scores[_BOTH] == pytest.approx(2 / 60)


# Rowids for the tie fixture: one chunk in each list, neither in both.
_VECTOR_TIE = 10
_KEYWORD_TIE = 20


def test_fuse_is_deterministic_and_scores_a_symmetric_tie_equally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two chunks each ranked 0 in exactly one list score identically — a genuine
    tie the fusion resolves the same way every call, so the downstream stable
    sort is deterministic — and re-running ``_fuse`` on the same index returns an
    identical mapping."""

    connection = _memory_index()
    _add_vector(connection, _VECTOR_TIE, _dense((0, 1.0)))
    _add_keyword(connection, _KEYWORD_TIE, "alpha")
    _stub_query_embedding(monkeypatch, _dense((0, 1.0)))

    scores = index._fuse(connection, "alpha")

    assert scores[_VECTOR_TIE] == pytest.approx(1 / 60)
    assert scores[_KEYWORD_TIE] == pytest.approx(1 / 60)
    assert index._fuse(connection, "alpha") == scores


# A fixed "today" so the recency assertions are exact and reproducible.
_TODAY = date(2026, 7, 13)


def test_recency_factor_is_monotonic_newer_never_below_older() -> None:
    """On the recency axis alone a newer entry never scores below an older one:
    ordered oldest to newest the factor is non-decreasing (entries past the
    one-year horizon share the floored value, which still satisfies this)."""

    ascending_dates = [
        "2020-01-01",  # years old — past the one-year horizon
        "2025-07-13",  # exactly one year — the horizon itself
        "2025-10-13",  # within the year
        "2026-04-13",  # more recent still
        "2026-07-13",  # today
    ]

    factors = [index._recency_factor(entry, _TODAY) for entry in ascending_dates]

    assert factors == sorted(factors)


def test_recency_factor_is_stable_at_the_boundaries() -> None:
    """A same-day entry gets the full boost; an entry exactly a year old, or
    older, gets none — the boost floors at the one-year horizon."""

    assert index._recency_factor("2026-07-13", _TODAY) == pytest.approx(1.3)
    assert index._recency_factor("2025-07-13", _TODAY) == pytest.approx(1.0)
    assert index._recency_factor("2000-01-01", _TODAY) == pytest.approx(1.0)


def test_recency_factor_pins_the_decay_constant_and_horizon() -> None:
    """An entry 100 days old scores 1 + 0.3·(1 − 100/365). The literals 0.3 and
    365 are written out here rather than read from the module, so a change to the
    recency weight or the horizon fails this test."""

    hundred_days_ago = index._recency_factor("2026-04-04", _TODAY)

    assert hundred_days_ago == pytest.approx(1 + 0.3 * (1 - 100 / 365))


def test_recency_factor_tolerates_malformed_and_absent_dates() -> None:
    """An unparseable or empty date is treated as neutral (factor 1.0) rather
    than raising: a Concept with no timestamp yields an empty date string, and
    recall must still be able to rank it."""

    for bad in ("", "not-a-date", "2026-13-40", "2026-02-30"):
        assert index._recency_factor(bad, _TODAY) == 1.0


def _chunk_row(heading: str, *, entry_date: str) -> sqlite3.Row:
    """A real ``sqlite3.Row`` carrying only the columns ``_cite`` reads, so the
    reranker can be exercised without a store, an ``index.db`` or the embedding
    model. The body after the heading gives ``_excerpt`` something to quote."""

    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    row: sqlite3.Row = connection.execute(
        "SELECT ? AS project_id, ? AS source, ? AS date, ? AS heading, ? AS text",
        (
            "proj-a",
            f"long-term/{entry_date}.md",
            entry_date,
            heading,
            f"{heading}\n\nA short body about the release cadence and the login rework.",
        ),
    ).fetchone()
    return row


def test_rerank_score_ignores_the_heading() -> None:
    """The reranker ranks by the fused match and recency alone: the former
    "session digest" (×1.2) and "aged out" (×0.9) heading weights are gone (issue
    #62, ADR 0023). Three chunks sharing a base score and date — a one-time
    digest, a plain capture and a one-time aged-out block — now score identically
    whatever their headings."""

    base = 0.05
    digest = index._cite(
        _chunk_row("Session digest of 2026-07-13", entry_date="2026-07-13"), base, query_date=_TODAY
    )
    capture = index._cite(
        _chunk_row("Release cadence", entry_date="2026-07-13"), base, query_date=_TODAY
    )
    aged_out = index._cite(
        _chunk_row("Aged out of short-term (2026-07-13)", entry_date="2026-07-13"),
        base,
        query_date=_TODAY,
    )

    assert digest.score == capture.score == aged_out.score


def test_rerank_score_is_the_fused_match_times_recency_only() -> None:
    """A chunk's rerank score is exactly its fused base score times the recency
    factor — nothing else multiplies in. A former "session digest" heading, which
    used to earn a ×1.2 boost, no longer changes the score."""

    base = 0.05
    scored = index._cite(
        _chunk_row("Session digest", entry_date="2026-04-04"), base, query_date=_TODAY
    )

    assert scored.score == pytest.approx(base * index._recency_factor("2026-04-04", _TODAY))


def test_no_heading_based_source_weight_remains() -> None:
    """The heading-based source-weight helper is removed, not merely bypassed, so
    no source-based weighting can silently return to the reranker (issue #62)."""

    assert not hasattr(index, "_source_weight")


def test_cite_returns_the_full_citation_shape() -> None:
    """Cited recall still carries its source, date, heading and a non-empty quoted
    excerpt through the reranker — collapsing the source weight must not thin the
    citation (issue #62, acceptance criterion 3)."""

    citation = index._cite(
        _chunk_row("Release cadence", entry_date="2026-06-01"), 0.05, query_date=_TODAY
    )

    assert citation.source == "long-term/2026-06-01.md"
    assert citation.date == "2026-06-01"
    assert citation.heading == "Release cadence"
    assert "release cadence" in citation.excerpt.lower()
