"""Distillation (Stage 5b): the bridge that promotes durable memory into
permanent Concepts (ADRs 0004, 0013, 0014, 0015, 0017).

Each fact is processed read-modify-write against the bundle: rejected if it is
instruction-shaped (never let an imperative become a standing Concept) or
tombstoned; deduplicated against an existing Concept about the same subject; and
otherwise created, or — when the fact has changed — used to supersede its
predecessor so recall returns exactly one current answer. Durable short-term
entries are promoted then evicted only after their Concept is verified on disk; a
failed promotion leaves the entry and is logged. Newly distilled Concepts queue
for the next session's announcement.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from mimer.bundle import Concept, Source, create_concept, list_concepts, mark_superseded
from mimer.failure_log import log_failure
from mimer.paths import store_root
from mimer.redaction import redact
from mimer.registry import project_dir
from mimer.shortterm import parse_short_term, render_short_term, short_term_path
from mimer.storeio import append_text, project_lock, write_atomic
from mimer.tombstones import is_tombstoned

DISTILLED_QUEUE_FILENAME = ".distilled-queue"

# Content words shorter than this, and these glue words, are ignored when
# deciding whether two facts are about the same subject.
_STOP = frozenset(
    [
        "the",
        "a",
        "an",
        "and",
        "or",
        "but",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "to",
        "of",
        "in",
        "on",
        "at",
        "for",
        "from",
        "with",
        "by",
        "we",
        "our",
        "you",
        "your",
        "it",
        "its",
        "this",
        "that",
        "these",
        "those",
        "now",
        "new",
        "then",
        "than",
        "as",
    ]
)

# Conservative markers of an imperative addressed to the agent (ADR 0014).
_INSTRUCTION_FIRST_WORDS = frozenset(
    {"always", "never", "please", "don't", "dont", "ensure", "avoid"}
)
_INSTRUCTION_MARKERS = (
    "you must",
    "you should",
    "you need to",
    "make sure",
    "be sure to",
    "remember to",
    "do not ",
)


@dataclass(frozen=True)
class DistillResult:
    """The outcome of distilling one fact."""

    status: str
    slug: str | None = None


def distill_fact(
    *,
    text: str,
    project_id: str,
    root: Path | None = None,
    scope: str = "project",
    citations: list[Source] | None = None,
    concept_type: str = "Fact",
    pinned: bool = False,
    confirmed: bool = False,
) -> DistillResult:
    """Distil one fact into permanent memory: create, extend, supersede or reject.

    Every fact is guarded identically — rejected when instruction-shaped
    (ADR 0014) or tombstoned (ADR 0012), deduplicated or superseded against an
    existing Concept about the same subject (ADR 0015). ``concept_type``,
    ``pinned`` and ``confirmed`` forward to :func:`create_concept` for the one
    case where a distilled fact seeds the pinned profile (bootstrap), so that
    seed passes the same guards as every other fact instead of bypassing them.
    """

    root = root or store_root()

    # Redact up front so every check and the stored Concept share one secret-free
    # form: the dedup and tombstone lookups compare like with like, and the title
    # is derived from redacted text rather than truncated raw — where a token
    # straddling the title cut could otherwise leave a fragment (issue #23).
    text = redact(text)

    if _is_instruction_shaped(text):
        return DistillResult("rejected-instruction")
    if is_tombstoned(text, project_id=project_id, root=root):
        return DistillResult("rejected-tombstoned")

    # Recall over the bundle first: is there an active Concept about this subject?
    predecessor = _same_subject_concept(text, project_id, root)
    if predecessor is not None and _normalise(predecessor.body) == _normalise(text):
        return DistillResult("duplicate", predecessor.slug)

    concept = create_concept(
        title=_title(text),
        body=text,
        concept_type=concept_type,
        origin=project_id,
        scope=scope,
        pinned=pinned,
        confirmed=confirmed,
        citations=citations,
        supersedes=predecessor.id if predecessor is not None else None,
        root=root,
    )

    if predecessor is not None:
        mark_superseded(predecessor.slug, concept.id, root)
        status = "superseded"
    else:
        status = "created"

    _record_distilled(project_id, concept.title, root)
    return DistillResult(status, concept.slug)


def distill_durable_entries(
    project_id: str, root: Path | None = None, *, scope: str = "project", today: date | None = None
) -> list[DistillResult]:
    """Promote durable short-term entries, evicting each only once its Concept is
    verified on disk; a failed promotion leaves the entry and is logged."""

    root = root or store_root()
    path = short_term_path(project_id, root)
    if not path.exists():
        return []

    results: list[DistillResult] = []
    with project_lock(project_id, root=root):
        sections = parse_short_term(path.read_text(encoding="utf-8"))
        for name, entries in sections.items():
            kept = []
            for entry in entries:
                if not entry.durable:
                    kept.append(entry)
                    continue
                result = _promote(entry.text, project_id, scope, root)
                results.append(result)
                # Evict only a fact that is now verifiably a Concept on disk.
                if result.status not in ("created", "superseded", "duplicate"):
                    kept.append(entry)
            sections[name] = kept
        write_atomic(path, render_short_term(project_id, sections))
    return results


def _promote(text: str, project_id: str, scope: str, root: Path) -> DistillResult:
    """Distil one durable entry, absorbing any failure so eviction is safe."""

    try:
        return distill_fact(text=text, project_id=project_id, scope=scope, root=root)
    except Exception as exc:  # noqa: BLE001 - a failed promotion must not lose the entry
        log_failure(f"distill: promotion failed for {text!r}: {exc!r}", root=root)
        return DistillResult("failed")


def _same_subject_concept(text: str, project_id: str, root: Path) -> Concept | None:
    """Find an active, visible Concept about the same subject as ``text``."""

    for concept in list_concepts(root):
        if concept.status != "active":
            continue
        if concept.scope != "global" and concept.origin != project_id:
            continue
        if _same_subject(text, concept.body):
            return concept
    return None


def _same_subject(a: str, b: str) -> bool:
    """Whether two facts are about the same subject, by content-word overlap."""

    words_a, words_b = _content_words(a), _content_words(b)
    if not words_a or not words_b:
        return False
    return len(words_a & words_b) / min(len(words_a), len(words_b)) >= 0.5


def _content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2 and w not in _STOP}


def _is_instruction_shaped(text: str) -> bool:
    """Whether text reads as an imperative to the agent rather than a fact."""

    lowered = text.strip().lower()
    words = lowered.split()
    if words and words[0] in _INSTRUCTION_FIRST_WORDS:
        return True
    return any(marker in lowered for marker in _INSTRUCTION_MARKERS)


def _normalise(text: str) -> str:
    return " ".join(text.lower().split())


def _title(text: str) -> str:
    """A readable Concept title derived from a fact."""

    collapsed = " ".join(text.split()).rstrip(".")
    return collapsed[:80]


def _queue_path(project_id: str, root: Path | None) -> Path:
    return project_dir(project_id, root or store_root()) / DISTILLED_QUEUE_FILENAME


def _record_distilled(project_id: str, title: str, root: Path | None) -> None:
    append_text(_queue_path(project_id, root), title)


def drain_distilled(project_id: str, root: Path | None = None) -> list[str]:
    """Return and clear the titles queued for the next session's announcement."""

    path = _queue_path(project_id, root)
    if not path.exists():
        return []
    items = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    path.unlink()
    return items


def distill_session(project_id: str, root: Path | None = None, *, scope: str = "project") -> None:
    """Opportunistic session-boundary distillation: promote durable entries."""

    distill_durable_entries(project_id, root=root, scope=scope)
