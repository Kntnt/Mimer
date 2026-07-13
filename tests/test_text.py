"""The shared text helpers (issue #19): one stopword set, one truncation helper
and one bullet-parser, each imported by the modules that used to keep a private
copy.

These tests pin the DRY contract the ticket asks for — that distillation and
recall reference the *same* stopword object, so they can never again drift into
classifying a word differently — and the behaviour of the three helpers the
scattered copies are consolidated into.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from mimer import distill, index
from mimer import text as mtext


def test_distill_and_index_share_one_stopword_set() -> None:
    """Distillation's subject-matcher and recall's keyword filter answer the same
    "is this a content word?" question, so they reference one frozenset — an
    identity check, so a re-declared private copy fails loudly (issue #19)."""

    assert distill._STOP is mtext.STOPWORDS
    assert index._STOPWORDS is mtext.STOPWORDS


def test_stopwords_is_the_union_of_the_two_legacy_sets() -> None:
    """The merged set is the union of the two hand-maintained lists that had
    drifted, so every word either module treated as glue stays glue — the
    deliberate merge choice recorded for the ticket (issue #19)."""

    # Words that lived only in distillation's list.
    for word in ("been", "these", "those", "now", "new", "then", "than"):
        assert word in mtext.STOPWORDS, word

    # Words that lived only in recall's list.
    for word in ("do", "does", "how", "into", "so", "their", "them", "they"):
        assert word in mtext.STOPWORDS, word
    for word in ("what", "when", "where", "which", "who", "why", "will"):
        assert word in mtext.STOPWORDS, word


def test_fts_query_drops_a_word_that_became_glue_for_recall() -> None:
    """The union pulled seven words (including "new") into recall's stopword set,
    so a keyword query whose only content word is one of them now yields no FTS
    match — recall leans on adjacent terms and semantic search rather than on the
    newly-glue word. This pins that behavioural consequence of the merge directly,
    without the embedding model the recall suite needs (issue #19)."""

    # A lone "new" was a content word for recall before the merge; now it is glue,
    # so the query has nothing left to keyword-search on.
    assert index._fts_query("new") is None

    # Beside a real content word the query still matches — on that word alone.
    assert index._fts_query("new releases") == '"releases"'


def test_truncate_returns_short_text_unchanged() -> None:
    assert mtext.truncate("a short line", 80) == "a short line"


def test_truncate_collapses_runs_of_whitespace() -> None:
    assert mtext.truncate("a   b\n\tc", 80) == "a b c"


def test_truncate_appends_marker_only_when_it_has_to_cut() -> None:
    assert mtext.truncate("abcdef", 3) == "abc…"
    assert mtext.truncate("abc", 3) == "abc"


def test_truncate_trims_whitespace_at_the_cut_before_the_marker() -> None:
    # "abc def"[:4] is "abc " — the trailing space is trimmed so the result never
    # reads "abc …".
    assert mtext.truncate("abc def", 4) == "abc…"


def test_truncate_marker_can_be_empty_for_a_hard_cut() -> None:
    assert mtext.truncate("abcdef", 3, marker="") == "abc"


def test_parse_bullets_extracts_items_and_skips_none_and_non_bullets() -> None:
    lines = ["- first", "- none", "", "  - second  ", "not a bullet", "-nobody"]
    assert mtext.parse_bullets(lines) == ["first", "second"]


def test_parse_bullets_with_only_the_none_sentinel_yields_nothing() -> None:
    assert mtext.parse_bullets(["- none", "- None"]) == []


def test_parse_bullets_applies_the_transform_before_the_empty_and_none_check() -> None:
    """A caller (the digest) neutralises each bullet before deciding it is empty
    or 'none', so the transform runs first: a transform that empties a value
    drops it, and one that yields 'none' drops it too (issue #19)."""

    result = mtext.parse_bullets(["- keep", "- drop"], transform=lambda t: "" if t == "drop" else t)
    assert result == ["keep"]


def test_resolve_project_fixture_returns_the_bound_project_id(
    resolve_project: Callable[[Path], str], project_dir: Path
) -> None:
    """The shared fixture replaces the resolve-then-assert helper copied across
    the test suite: it resolves a cwd to a non-None project id (issue #19)."""

    project_id = resolve_project(project_dir)
    assert isinstance(project_id, str) and project_id
