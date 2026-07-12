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
