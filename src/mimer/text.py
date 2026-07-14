"""Shared text helpers: one authoritative home for the pieces of knowledge that
had drifted into copies across the memory stages (issue #19).

"Collapse and truncate" lived in three places and "parse a Markdown bullet list"
in two; consolidating each here gives every caller one source to import rather than
a copy to keep in step. The stopword set here is the *retrieval* set — recall's
FTS query-term selection is its one consumer. Fact identity does not draw on it:
the matcher is the one home of "same fact?" and "same subject?" and owns its own
stopword set (issues #18, #52). The two sets are deliberately separate, so retuning
retrieval never silently moves what the matcher treats as a content word.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

# The retrieval stopword set: the glue words dropped when choosing which terms to
# keyword-search on — recall's FTS query, its one consumer. It is *not* the whole
# system's stopword set: fact identity lives in the matcher, which owns its own
# (issues #18, #52), so retuning this set never moves what distillation treats as a
# content word. The set is the union of the two lists distillation and recall once
# maintained separately, kept whole so recall loses no glue word it ever had
# (issue #19). One consequence, chosen knowingly: "new" (from distillation's old
# list) is glue for recall too, so a keyword query leans on the word beside it and
# on semantic search rather than on "new" itself.
STOPWORDS: frozenset[str] = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "but",
        "by",
        "do",
        "does",
        "for",
        "from",
        "how",
        "in",
        "into",
        "is",
        "it",
        "its",
        "new",
        "now",
        "of",
        "on",
        "or",
        "our",
        "so",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "these",
        "they",
        "this",
        "those",
        "to",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "you",
        "your",
    ]
)


def truncate(text: str, limit: int, *, marker: str = "…") -> str:
    """Collapse runs of whitespace to single spaces and cut to ``limit`` chars,
    appending ``marker`` only when the text had to be cut.

    The whitespace at a cut point is trimmed before the marker, so a truncated
    string never reads ``"word …"``. Pass ``marker=""`` for a hard cut with no
    ellipsis — a fixed-width title rather than a visibly abridged excerpt.

    Args:
        text: The raw text; internal whitespace is collapsed first.
        limit: The maximum number of characters of the collapsed text to keep.
        marker: Appended only when a cut happens; ``"…"`` by default.
    """

    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[:limit].rstrip() + marker


def parse_bullets(
    lines: Iterable[str], *, transform: Callable[[str], str] | None = None
) -> list[str]:
    """Extract the text of each Markdown bullet, dropping blanks and the ``none``
    sentinel.

    A model reply that lists one item per ``"- "`` line, with ``"- none"`` for
    "nothing", is parsed to the list of item texts. ``transform`` (the boundary
    pass passes :func:`mimer.framing.neutralise`) is applied to each item *before*
    the empty/``none`` test, so a transform that empties a value drops it rather
    than letting a defanged artefact through.

    Args:
        lines: The reply's lines; each is stripped before the ``"- "`` test.
        transform: Optional per-item transform applied ahead of the checks.
    """

    texts: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        text = stripped[2:].strip()
        if transform is not None:
            text = transform(text)
        if text and text.lower() != "none":
            texts.append(text)
    return texts
