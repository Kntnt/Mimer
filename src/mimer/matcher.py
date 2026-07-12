"""The one shared answer to "are these two texts the same fact?" (issue #18).

Forgetting is a trust feature (ADR 0012): a fact removed by ``forget`` must stay
gone whether it is later written, recalled or re-distilled. That only holds if
every site that asks "same fact?" answers identically — so this module is the
single implementation the tombstone check, recall suppression and forget all
delegate to.

The test has two parts. Two texts are trivially the same fact when they are
equal once case and whitespace are normalised — this settles identical facts,
including short ones the guard below would otherwise refuse. Otherwise they are
the same fact when the *shorter* one is contained in the longer: almost all of
its content words appear there. Using the shorter text as the denominator is
what lets a forgotten fact be recognised inside a much larger recall chunk that
bundles many facts (a captured turn, an aged-out block) — a symmetric overlap
against the whole chunk drops below the bar and lets the fact resurface. The
specificity guard is the counterweight: a short, generic phrase (``uses redis``)
carries too few words to fuzzy-match a longer text that merely contains them, so
tombstoning it does not over-suppress unrelated memories.

Tokenisation keeps non-ASCII letters, so a non-English fact is matched on its
real content words rather than on the ASCII fragments a ``[a-z0-9]+`` scan leaves
behind — Mimer's users are not English-only.
"""

from __future__ import annotations

import re

# A text is contained in another when at least this fraction of its content words
# is present there. Tuned so a lightly reworded restatement clears the bar.
_CONTAINMENT_THRESHOLD = 0.5

# The shorter text must carry at least this many content words for a fuzzy
# (non-exact) match. Below it, only the exact-identity path can match — so a short
# tombstone never suppresses a longer text that merely contains its few words.
_MIN_TOKENS_FOR_OVERLAP = 3

# Content words: maximal runs of Unicode letters and digits (underscore excluded),
# case-folded. Non-ASCII letters are kept deliberately (see the module docstring).
_WORD_RE = re.compile(r"[^\W_]+")


def _tokens(text: str) -> frozenset[str]:
    """The set of content words in ``text``, lowercased; order and repeats drop out."""

    return frozenset(_WORD_RE.findall(text.lower()))


def _normalise(text: str) -> str:
    """Case- and whitespace-normalised form, for the exact-identity comparison."""

    return " ".join(text.lower().split())


def is_same_fact(a: str, b: str) -> bool:
    """Whether two texts state the same fact, up to trivial rewording.

    Symmetric. Two texts match when they are equal once normalised, or when the
    shorter one's content words are almost wholly present in the longer and it
    carries enough words to be specific. Because the shorter text is the
    denominator, a forgotten fact matches even when it sits inside a much larger,
    multi-fact chunk — while a short, generic phrase (guarded by
    :data:`_MIN_TOKENS_FOR_OVERLAP`) does not match a longer text that merely
    contains it.

    Args:
        a: One text (a candidate fact, a stored memory, a recall chunk or a tombstone).
        b: The other text.

    Returns:
        ``True`` when the two texts are the same fact under the shared semantics.
    """

    # Trivial identity: equal once case and whitespace are normalised. Handles
    # short facts too, which the specificity guard below deliberately refuses to
    # match on partial overlap.
    if _normalise(a) == _normalise(b):
        return True

    # Directional containment: is the shorter text's content almost wholly present
    # in the longer? A too-short shorter text is not specific enough to match on
    # overlap alone and only the exact path above can match it.
    shorter, longer = sorted((_tokens(a), _tokens(b)), key=len)
    if len(shorter) < _MIN_TOKENS_FOR_OVERLAP:
        return False
    return len(shorter & longer) / len(shorter) >= _CONTAINMENT_THRESHOLD
