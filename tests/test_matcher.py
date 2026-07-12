"""Tests for the shared "same fact?" matcher (issue #18): the single answer that
tombstoning, recall suppression and forget all delegate to, so a forgotten fact
means the same thing whether it is being written, recalled or re-distilled.

The two behaviours the previous per-site logic got wrong are pinned here: a
reworded restatement of a fact must still count as the same fact (exact-equality
let it slip through), and a short phrase must not count as the same fact as a
longer, unrelated text that merely contains it (substring over-matched).
"""

from __future__ import annotations

from mimer.matcher import is_same_fact


def test_identical_text_is_the_same_fact() -> None:
    """A fact is trivially the same fact as itself."""

    assert is_same_fact("The prototype used a Redis cache.", "The prototype used a Redis cache.")


def test_normalisation_ignores_case_and_whitespace() -> None:
    """Casing and runs of whitespace do not change a fact's identity."""

    assert is_same_fact("The  Staging   Password is HUNTER2", "the staging password is hunter2")


def test_reworded_fact_is_recognised_as_the_same_fact() -> None:
    """A reworded restatement keeps the content words, so it is the same fact.

    This is the case exact-equality missed: forgetting the first must also forget
    the second.
    """

    assert is_same_fact(
        "The prototype used a Redis cache.",
        "We used Redis for the prototype cache",
    )


def test_short_phrase_is_not_the_same_fact_as_a_longer_unrelated_text() -> None:
    """A short phrase inside a longer, unrelated text is not the same fact.

    This is the case substring matching got wrong: it hid every memory that merely
    contained the phrase.
    """

    assert not is_same_fact(
        "uses redis",
        "The analytics pipeline uses Redis Streams to buffer events before the nightly load.",
    )


def test_unrelated_facts_are_not_the_same_fact() -> None:
    """Two facts about different subjects are not the same fact."""

    assert not is_same_fact(
        "The invoice for the cloud bill is due next Tuesday.",
        "We refactored the login system to use JWT access tokens.",
    )


def test_matcher_is_symmetric() -> None:
    """The order of the two texts never changes the answer."""

    a = "The prototype used a Redis cache."
    b = "We used Redis for the prototype cache"
    assert is_same_fact(a, b) == is_same_fact(b, a)


def test_two_short_facts_sharing_one_word_are_not_the_same_fact() -> None:
    """Two short facts that share a single word are distinct, not the same fact."""

    assert not is_same_fact("uses redis", "uses postgres")


def test_non_ascii_reworded_fact_is_recognised_as_the_same_fact() -> None:
    """A reworded non-ASCII (Swedish) fact is still the same fact (issue #18).

    The tokenizer keeps non-ASCII letters, so a non-English fact is matched on its
    real content words rather than on the ASCII fragments a ``[a-z0-9]+`` scan would
    leave behind.
    """

    assert is_same_fact(
        "Prototypen använde en Redis-cache.",
        "Vi använde Redis för prototypens cache",
    )


def test_two_different_non_ascii_facts_are_not_the_same_fact() -> None:
    """Two unrelated non-ASCII facts are distinct, so tokenisation is not collapsing
    different words to the same ASCII fragment."""

    assert not is_same_fact(
        "Lösenordet är hemligt och roteras varje månad.",
        "Fakturan för molnräkningen förfaller nästa tisdag.",
    )


def test_generic_phrase_does_not_match_a_contradictory_longer_text() -> None:
    """A short generic forget must not suppress a longer, contradicting memory (issue #18).

    ``we use redis`` shares only the function words ``we``/``use`` with a memory that
    in fact says the opposite (Postgres). Counting those glue words as content
    over-suppressed a directly contradictory fact — the harm ADR 0012 exists to
    prevent.
    """

    assert not is_same_fact(
        "we use redis",
        "We should use Postgres for the main store, and we will use it heavily.",
    )


def test_same_subject_different_value_is_not_the_same_fact() -> None:
    """Two comparable facts differing only in the distinguishing value contradict (issue #18).

    Both texts carry three or more content words and share subject and verb, so the
    old substring test never matched them and token overlap alone clears the 50 %
    bar (``port`` 8080 vs 9090 shares three of four content words). Treating them as
    the same fact would tombstone the old value and hide the corrected one — the
    over-suppression ADR 0012 exists to prevent. A lone swapped content word is a
    value substitution, not a rewording, so these are distinct facts.
    """

    assert not is_same_fact("The API runs on port 8080", "The API runs on port 9090")
    assert not is_same_fact("the meeting is on monday at noon", "the meeting is on tuesday at noon")
    assert not is_same_fact("backup runs nightly at 2am", "backup runs weekly at 2am")
    assert not is_same_fact("deploy uses docker", "the deploy uses podman")


def test_stopword_heavy_phrase_does_not_match_a_longer_text_containing_it() -> None:
    """A phrase that is almost all function words is too generic to be a fact (issue #18).

    ``we use it`` occurs verbatim inside the longer text, but it carries a single
    content word — far too generic to identify a fact, so it must not suppress the
    unrelated memory that happens to contain it.
    """

    assert not is_same_fact(
        "we use it",
        "When we run the migration we use it only after the backup is verified.",
    )


def test_short_content_words_scattered_in_a_longer_text_are_not_the_same_fact() -> None:
    """Three content words scattered across an unrelated text are not the same fact (issue #18).

    Every content word of ``deploy window friday`` appears in the longer text, but
    dispersed across unrelated clauses rather than as the forgotten fact. Whole-set
    containment over-suppressed here; only a genuine restatement (a contiguous run
    or near-total overlap) should match.
    """

    assert not is_same_fact(
        "deploy window friday",
        "The office moved the deploy schedule so the testing window is wider, "
        "and the celebration happens on friday.",
    )


def test_forgotten_fact_embedded_verbatim_in_a_larger_chunk_is_the_same_fact() -> None:
    """A forgotten fact quoted verbatim inside a much larger chunk is the same fact (issue #18).

    Recall chunks bundle a whole turn or an aged-out block, so a forgotten fact
    routinely sits inside a chunk many times its size. The matcher must still
    recognise it, or the fact resurfaces in that chunk and the forget is defeated.
    """

    assert is_same_fact(
        "the staging password is hunter2",
        "Assistant: tokens live in redis and the staging password is hunter2 until "
        "rotation. User: how do we handle secrets?",
    )
