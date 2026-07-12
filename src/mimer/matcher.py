"""The one shared answer to "are these two texts the same fact?" (issue #18).

Forgetting is a trust feature (ADR 0012): a fact removed by ``forget`` must stay
gone whether it is later written, recalled or re-distilled. That only holds if
every site that asks "same fact?" answers identically — so this module is the
single implementation the tombstone check, recall suppression and forget all
delegate to.

The test is a length-guarded token overlap: two texts are the same fact when a
large enough fraction of their combined content words is shared. This recognises
a reworded restatement of a fact (which keeps the content words) as the same
fact, yet a short phrase does not match a longer, unrelated text that merely
contains it — the union in the denominator is the length guard that a plain
substring test lacked.
"""

from __future__ import annotations

import re

# Two texts count as the same fact when at least this fraction of their combined
# content words is shared (Jaccard overlap). Tuned so a lightly reworded
# restatement clears the bar while a short phrase inside a much longer, unrelated
# text falls well below it.
_SAME_FACT_THRESHOLD = 0.5

# Content words for overlap: maximal runs of letters and digits, case-folded.
_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> frozenset[str]:
    """The set of content words in ``text``, lowercased; order and repeats drop out."""

    return frozenset(_WORD_RE.findall(text.lower()))


def is_same_fact(a: str, b: str) -> bool:
    """Whether two texts state the same fact, up to trivial rewording.

    Symmetric. Compares the two texts by the Jaccard overlap of their content-word
    sets: identical or lightly reworded facts share most of their words and match,
    while a short text and a much longer one share only a small fraction of their
    union and do not.

    Args:
        a: One text (a candidate fact, a stored memory or a tombstone).
        b: The other text.

    Returns:
        ``True`` when the two texts are the same fact under the shared semantics.
    """

    # Reduce both texts to their content-word sets for the overlap comparison.
    tokens_a = _tokens(a)
    tokens_b = _tokens(b)
    union = tokens_a | tokens_b

    # Wordless texts (punctuation only) have nothing to overlap and would divide by
    # zero; fall back to a normalised exact comparison for that degenerate input.
    if not union:
        return " ".join(a.lower().split()) == " ".join(b.lower().split())

    return len(tokens_a & tokens_b) / len(union) >= _SAME_FACT_THRESHOLD
