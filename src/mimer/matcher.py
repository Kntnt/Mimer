"""The one shared answer to "are these two texts the same fact?" (issue #18).

Forgetting is a trust feature (ADR 0012): a fact removed by ``forget`` must stay
gone whether it is later written, recalled or re-distilled. That only holds if
every site that asks "same fact?" answers identically — so this module is the
single implementation the tombstone check, recall suppression and forget all
delegate to.

Two texts are the same fact when any of three tests holds:

* **Identity** — they are equal once case and whitespace are normalised. This
  settles identical facts, including short ones the specificity guard below would
  otherwise refuse.
* **Restatement** — they share at least half of the *larger* text's content
  words. Dividing by the larger set means this fires only for two texts of
  comparable size that overlap heavily — a reworded fact — and never for a small
  phrase whose words happen to scatter across a much larger, unrelated text. One
  case is deliberately excluded: two facts of equal length that differ by exactly
  one content word are a *value substitution* (``port 8080`` → ``port 9090``,
  ``monday`` → ``tuesday``), not a rewording — they contradict. Matching them
  would tombstone the old fact and suppress its correction, the over-suppression
  ADR 0012 forbids, so a lone swapped word is never treated as a restatement.
* **Quotation** — the smaller text occurs verbatim, as a contiguous run, inside
  the larger. This is what lets a forgotten fact be recognised inside a much
  larger recall chunk that bundles many facts (a captured turn, an aged-out
  block), where the restatement ratio is diluted below the bar.

Content words exclude function words (``the``, ``we``, ``is`` …); a fact's
identity lives in its nouns and verbs, not its glue. The specificity guard is the
counterweight to over-suppression: a phrase carrying fewer than
:data:`_MIN_CONTENT_WORDS` content words (``uses redis``, ``we use it``) is too
generic to identify a fact, so only the exact-identity path can match it — it
never suppresses a longer text that merely contains or scatters its few words.

Two deliberate limitations, so callers know the guarantee's real shape:

* Matching is on exact word forms — there is no stemming. A rewording that
  *inflects* its content words (``cache`` → ``caching``, ``used`` → ``uses``)
  changes the token and can slip through as a different fact. Restatements that
  keep the word forms and only reorder them are caught; inflected ones are not.
* Tokenisation keeps non-ASCII letters, so a non-English fact is matched on its
  real content words rather than on the ASCII fragments a ``[a-z0-9]+`` scan
  would leave behind — Mimer's users are not English-only. Its stopword list is
  English, so a non-English fact's function words count as content; this only
  makes the matcher stricter (more specific), never looser.
"""

from __future__ import annotations

import re

# Two texts are the same fact when they share at least this fraction of the larger
# text's content words. The larger set as denominator keeps the ratio high only for
# comparable-size texts, so it fires for a reworded fact but not for a short phrase
# lost in a much larger one.
_OVERLAP_THRESHOLD = 0.5

# A text must carry at least this many content words to be matched on anything but
# exact identity. Below it a phrase is too generic to name a fact, so it never
# suppresses a longer text that merely contains or scatters its words.
_MIN_CONTENT_WORDS = 3

# Content words: maximal runs of Unicode letters and digits (underscore excluded),
# case-folded. Non-ASCII letters are kept deliberately (see the module docstring).
_WORD_RE = re.compile(r"[^\W_]+")

# English function words that carry no fact identity. Counting them as content let
# a generic phrase fuzzy-match on shared glue (``we``/``use``), so they are stripped
# before overlap and the specificity guard are measured. Kept local to this module:
# the matcher is the shared prefactor other sites depend on, so it owns its own
# notion of "which words matter" rather than reaching into a higher layer.
_STOP = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "so",
        "as",
        "if",
        "then",
        "than",
        "because",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "am",
        "do",
        "does",
        "did",
        "done",
        "has",
        "have",
        "had",
        "will",
        "would",
        "shall",
        "should",
        "can",
        "could",
        "may",
        "might",
        "must",
        "to",
        "of",
        "in",
        "on",
        "at",
        "for",
        "from",
        "with",
        "by",
        "into",
        "onto",
        "over",
        "under",
        "about",
        "after",
        "before",
        "until",
        "while",
        "when",
        "we",
        "our",
        "us",
        "ours",
        "you",
        "your",
        "yours",
        "i",
        "me",
        "my",
        "mine",
        "he",
        "him",
        "his",
        "she",
        "her",
        "hers",
        "it",
        "its",
        "they",
        "them",
        "their",
        "theirs",
        "this",
        "that",
        "these",
        "those",
        "not",
        "no",
        "only",
        "just",
        "also",
        "very",
        "too",
        "now",
        "here",
        "there",
        "up",
        "down",
        "out",
    }
)


def _content_tokens(text: str) -> frozenset[str]:
    """The set of content words in ``text``: lowercased, stopwords removed.

    Order and repeats drop out; function words drop out. What remains is the nouns
    and verbs that carry a fact's identity.
    """

    return frozenset(_WORD_RE.findall(text.lower())) - _STOP


def _normalise(text: str) -> str:
    """Case- and whitespace-normalised form, for the identity and quotation tests."""

    return " ".join(text.lower().split())


def is_same_fact(a: str, b: str) -> bool:
    """Whether two texts state the same fact, up to trivial rewording.

    Symmetric. Two texts match when they are equal once normalised, when they share
    at least :data:`_OVERLAP_THRESHOLD` of the larger one's content words (a
    reworded restatement), or when the smaller occurs verbatim inside the larger (a
    forgotten fact quoted inside a much larger, multi-fact chunk). A text carrying
    fewer than :data:`_MIN_CONTENT_WORDS` content words is too generic to match on
    anything but exact identity, so a short phrase never over-suppresses a longer,
    unrelated text. Two equal-length facts differing by a single content word are a
    value substitution, not a restatement, so they are *not* the same fact — matching
    them would suppress a fact's own correction (see the module docstring).

    Args:
        a: One text (a candidate fact, a stored memory, a recall chunk or a tombstone).
        b: The other text.

    Returns:
        ``True`` when the two texts are the same fact under the shared semantics.
    """

    # Identity: equal once case and whitespace are normalised. Settles identical
    # facts, including short ones the specificity guard below refuses to fuzzy-match.
    if _normalise(a) == _normalise(b):
        return True

    # Specificity guard: a text too short on content words is too generic to be a
    # fact, so nothing but the exact path above may match it.
    smaller, larger = sorted((_content_tokens(a), _content_tokens(b)), key=len)
    if len(smaller) < _MIN_CONTENT_WORDS:
        return False

    # Restatement: comparable-size texts that share most of their content words — a
    # reworded fact. The larger set as denominator keeps a small phrase scattered
    # across a big text below the bar while a genuine rewording clears it. But two
    # facts of equal length differing by exactly one content word are a value
    # substitution ("port 8080" → "port 9090"), not a rewording: they contradict.
    # Matching them would tombstone the old fact and suppress its correction — the
    # over-suppression ADR 0012 forbids — so a lone swapped word is never a restatement.
    shared = len(smaller & larger)
    is_value_substitution = len(smaller) == len(larger) and shared == len(smaller) - 1
    if not is_value_substitution and shared / len(larger) >= _OVERLAP_THRESHOLD:
        return True

    # Quotation: the smaller text quoted verbatim inside the larger — a forgotten
    # fact bundled into a much larger chunk, where the ratio above is diluted away.
    return _normalise(a) in _normalise(b) or _normalise(b) in _normalise(a)
