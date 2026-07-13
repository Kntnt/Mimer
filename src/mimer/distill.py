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

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from mimer import clock
from mimer.bundle import Concept, Source, create_concept, list_concepts
from mimer.failure_log import log_failure
from mimer.longterm import append_entry
from mimer.matcher import is_same_subject, normalised
from mimer.paths import store_root
from mimer.redaction import redact
from mimer.registry import Registry, project_dir
from mimer.shortterm import Entry, rewrite_sections, short_term_path
from mimer.storeio import append_text, project_lock, write_atomic
from mimer.text import truncate
from mimer.tombstones import is_tombstoned

# The on-disk announcement-queue file. The name predates the "Announcement
# queue" term (CONTEXT.md) and stays as-is: renaming it would need a store
# migration for zero gain.
ANNOUNCEMENT_QUEUE_FILENAME = ".distilled-queue"

# A Concept title is a fixed-width label; a longer fact is hard-cut to this.
_TITLE_CHARS = 80

# A fact may supersede a predecessor only when the predecessor is not broader-scoped:
# a project-scoped fact must never narrow a global Concept, which would mark it
# dropped from recall in every other project (issue #29). Higher rank = broader.
_SCOPE_RANK = {"project": 0, "global": 1}

# Markers of an imperative addressed to the agent (ADR 0014). This filter is
# advisory: it is a best-effort pre-filter, not the gate. The gate is the
# structural framing in ``mimer.framing``, applied on every surface that
# re-presents memory — the session-start snapshot, ``mimer-recall`` and the
# ``mimer-manage`` inspection surface — so a directive that slips through here
# is still shown as inert, fenced data rather than a command to obey. The
# markers therefore target phrasings that are unambiguously agent-directed —
# rather than a first-word denylist, which wrongly rejected plain facts such as
# "Always use uv" while letting "Standing policy: …" through (issue #36).
_INSTRUCTION_MARKERS = (
    "you must",
    "you should",
    "you need to",
    "you are required to",
    "you are to ",
    "make sure",
    "be sure to",
    "remember to",
    "do not ",
    "under no circumstances",
    "standing policy",
    "it is required that",
    "it is mandatory",
    "the correct behaviour is",
    "the correct behavior is",
    "the agent must",
    "the agent should",
)


@dataclass(frozen=True)
class DistillResult:
    """The outcome of distilling one fact."""

    status: str
    slug: str | None = None


# The fact now lives on disk as a Concept, so its durable short-term entry has
# done its job and can leave.
_PROMOTED_STATUSES = frozenset({"created", "superseded", "duplicate"})

# The fact will never become a Concept — an imperative (ADR 0014) or a forgotten
# fact re-remembered (ADR 0012). Keeping its durable entry would strand it in
# short-term forever, re-rejected every session end and never cap-evicted, so it
# is aged out to the daily log instead.
_REJECTED_STATUSES = frozenset({"rejected-instruction", "rejected-tombstoned"})

# The one non-terminal status: distillation raised (logged by _promote) and the
# durable entry stays for a retry next session. Every other status distill_fact
# returns is terminal — promoted or rejected — so the three sets above and this
# one must jointly exhaust its outcomes; the classifier fails loud on any other.
_TRANSIENT_STATUS = "failed"


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

    # Honour the project's distill-to-global switch: a project that keeps its
    # knowledge in-house never promotes a fact with global scope (ADR 0013).
    if scope == "global" and not Registry.load(root).distill_to_global_enabled(project_id):
        scope = "project"

    # Redact up front so every check and the stored Concept share one secret-free
    # form: the dedup and tombstone lookups compare like with like, and the title
    # is derived from redacted text rather than truncated raw — where a token
    # straddling the title cut could otherwise leave a fragment (issue #23).
    text = redact(text)

    if _is_instruction_shaped(text):
        return DistillResult("rejected-instruction")
    if is_tombstoned(text, project_id=project_id, root=root):
        return DistillResult("rejected-tombstoned")

    # Recall over the bundle first: is there an active Concept about this subject
    # that this fact may safely dedup against or supersede (same or narrower scope)?
    predecessor = _same_subject_concept(text, project_id, scope, root)
    if predecessor is not None and normalised(predecessor.body) == normalised(text):
        return DistillResult("duplicate", predecessor.slug)

    # Create the successor and retire the predecessor as one atomic unit: when the
    # fact has changed, create_concept flips the old Concept to superseded and writes
    # the new one under a single bundle-lock acquisition, so recall never sees two
    # current answers on the subject and a failure cannot strand a live pair (#30).
    concept = create_concept(
        title=_title(text),
        body=text,
        concept_type=concept_type,
        origin=project_id,
        scope=scope,
        pinned=pinned,
        confirmed=confirmed,
        citations=citations,
        supersede=predecessor,
        root=root,
    )

    status = "superseded" if predecessor is not None else "created"
    _queue_announcement(project_id, concept.title, root)
    return DistillResult(status, concept.slug)


def distill_durable_entries(
    project_id: str, root: Path | None = None, *, scope: str = "project", today: date | None = None
) -> list[DistillResult]:
    """Promote durable short-term entries, evicting each only once its Concept is
    verified on disk; a failed promotion leaves the entry and is logged.

    An entry distillation *permanently* rejects — an imperative, or a forgotten
    fact re-remembered — will never become a Concept, so it is evicted too and
    aged out verbatim to today's daily log rather than stranded in short-term to
    be re-rejected on every session end (the cap never evicts a durable entry
    either). Only a transient failure keeps the entry, for a later retry.
    """

    root = root or store_root()
    day = today or clock.today()
    path = short_term_path(project_id, root)
    if not path.exists():
        return []

    results: list[DistillResult] = []

    def distil(sections: dict[str, list[Entry]]) -> dict[str, list[Entry]]:
        rejected: list[Entry] = []
        for name, entries in sections.items():
            kept = []
            for entry in entries:
                if not entry.durable:
                    kept.append(entry)
                    continue
                result = _promote(entry.text, project_id, scope, root)
                results.append(result)
                # Promoted entries are gone (their Concept is on disk); permanently
                # rejected ones are aged out below; a transient failure is retried.
                if result.status in _PROMOTED_STATUSES:
                    continue
                if result.status in _REJECTED_STATUSES:
                    rejected.append(entry)
                    continue
                if result.status == _TRANSIENT_STATUS:
                    kept.append(entry)
                    continue

                # A status none of the sets recognise means distill_fact grew a new
                # terminal outcome without classifying it here — fail loud rather
                # than fall through to "kept" and silently strand the entry.
                raise RuntimeError(f"unclassified distillation status: {result.status!r}")
            sections[name] = kept

        # Age the rejected entries out to the daily log before short-term is
        # rewritten, so a crash never leaves one absent from both places (ADR 0017).
        if rejected:
            append_entry(project_id, day.isoformat(), _rejected_block(rejected, day), root)
        return sections

    rewrite_sections(project_id, distil, root=root)
    return results


def _rejected_block(rejected: list[Entry], today: date) -> str:
    """Render a daily-log block holding entries distillation permanently rejected."""

    lines = [f"## Rejected by distillation ({today.isoformat()})"]
    lines.extend(f"- [{entry.date}] {entry.text}" for entry in rejected)
    return "\n".join(lines) + "\n"


def _promote(text: str, project_id: str, scope: str, root: Path) -> DistillResult:
    """Distil one durable entry, absorbing any failure so eviction is safe."""

    try:
        return distill_fact(text=text, project_id=project_id, scope=scope, root=root)
    except Exception as exc:  # noqa: BLE001 - a failed promotion must not lose the entry
        # Log the failure by a stable fact identifier and the exception type, never
        # the content: the log is surfaced by `mimer-manage health`, and an exception
        # repr can quote the failing fact — reintroducing memory that redaction cannot
        # recognise (personal data, plain prose), not only shape-detectable secrets (#24).
        identifier = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
        log_failure(
            f"distill: promotion failed for fact {identifier}: {type(exc).__name__}", root=root
        )
        return DistillResult("failed")


def _same_subject_concept(text: str, project_id: str, scope: str, root: Path) -> Concept | None:
    """Find the active, visible Concept a ``scope``-scoped fact should act on.

    Subject matching is the matcher's job (:func:`mimer.matcher.is_same_subject`);
    this function is the supersession *policy* over its answer. An identical Concept
    is returned regardless of scope, so an incoming fact deduplicates against it
    rather than writing a second copy. Otherwise only a Concept that is *not*
    broader-scoped than the incoming fact is returned as a supersession target: a
    project-scoped fact must never narrow a global Concept and drop it from recall
    everywhere (issue #29). A broader same-subject Concept is left untouched — the
    fact is created alongside it instead.
    """

    supersedable: Concept | None = None
    for concept in list_concepts(root):
        if concept.status != "active":
            continue
        if concept.scope != "global" and concept.origin != project_id:
            continue
        if not is_same_subject(text, concept.body):
            continue
        # An identical Concept is a duplicate whatever its scope — dedup against it
        # instead of minting a redundant copy.
        if normalised(concept.body) == normalised(text):
            return concept
        # Otherwise this Concept would be superseded, which is only safe when it is
        # not broader-scoped than the incoming fact.
        if supersedable is None and _SCOPE_RANK[concept.scope] <= _SCOPE_RANK[scope]:
            supersedable = concept
    return supersedable


def _is_instruction_shaped(text: str) -> bool:
    """Whether text reads as an imperative to the agent rather than a fact.

    Advisory only: the structural gate is the framing in ``mimer.framing``,
    applied on every surface that re-presents memory — snapshot injection,
    recall and inspection. A false negative here is caught there, so this errs
    towards admitting facts (``Always use uv``) over rejecting them.
    """

    lowered = text.strip().lower()
    return any(marker in lowered for marker in _INSTRUCTION_MARKERS)


def _title(text: str) -> str:
    """A readable Concept title derived from a fact: a hard-cut, ellipsis-free
    fixed-width line with any trailing period dropped.

    The period is stripped after whitespace is collapsed but before the cut, so a
    short fact ending in "." loses it; the cut is ellipsis-free because a title is
    a fixed-width label, not a visibly abridged excerpt."""

    collapsed = " ".join(text.split()).rstrip(".")
    return truncate(collapsed, _TITLE_CHARS, marker="")


def _queue_path(project_id: str, root: Path | None) -> Path:
    return project_dir(project_id, root or store_root()) / ANNOUNCEMENT_QUEUE_FILENAME


def _queue_announcement(project_id: str, title: str, root: Path | None) -> None:
    append_text(_queue_path(project_id, root), title)


@contextmanager
def announcements(project_id: str, root: Path | None = None) -> Iterator[list[str]]:
    """Yield the titles queued for this session's announcement line; on clean
    exit clear exactly those titles — at-least-once (ADR 0014, #40). An
    exception inside the block leaves the queue intact, so the notice is
    re-announced next session rather than lost.

    Locking is unchanged (ADR 0011): the peek is an unlocked read and the clear a
    locked read-modify-write that re-reads the live queue and removes only the
    yielded titles, so a title enqueued concurrently between peek and clear
    survives. The project lock is never held across the yield.
    """

    queued = _peek_announcements(project_id, root)
    yield queued
    _clear_announcements(project_id, queued, root)


def _peek_announcements(project_id: str, root: Path | None = None) -> list[str]:
    """Return the titles queued for the next session's announcement, without
    clearing the queue.

    Reading and clearing are split so the announcement can be cleared only after
    the snapshot that carries it has been emitted: an exception between the peek
    and the clear leaves the queue, and the notice is re-announced next session
    rather than lost — at-least-once, never zero (ADR 0014, #40). The
    :func:`announcements` context manager sequences the two; keeping the locked
    clear its own function lets it be exercised in isolation.
    """

    path = _queue_path(project_id, root)
    if not path.exists():
        return []
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _clear_announcements(project_id: str, emitted: list[str], root: Path | None = None) -> None:
    """Remove exactly the announcements already emitted, leaving any enqueued
    concurrently between the peek and this call for a later session.

    This drops only the emitted titles, never the whole queue — the silent loss
    #40 exists to prevent, from an announcement a capture or digest writer
    appends between :func:`_peek_announcements` and here. Each emitted title
    removes its first matching queued line and no more, so a title enqueued
    concurrently is absent from ``emitted`` and survives to the next session
    (at-least-once, ADR 0014).

    The re-read and rewrite run under the project lock so the read-modify-write
    cannot clobber a concurrent distiller's append: that writer enqueues while
    holding the same lock, so it and this clear serialise (ADR 0011).
    """

    if not emitted:
        return

    path = _queue_path(project_id, root)

    # Re-read the live queue under the lock, drop only the emitted titles, and
    # write back the remainder — a concurrently enqueued title is not in emitted,
    # so it stays; when nothing remains the queue file is removed.
    with project_lock(project_id, root=root):
        if not path.exists():
            return
        remaining = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        for title in emitted:
            if title in remaining:
                remaining.remove(title)
        if remaining:
            write_atomic(path, "\n".join(remaining) + "\n")
        else:
            path.unlink(missing_ok=True)


def distill_session(project_id: str, root: Path | None = None, *, scope: str = "project") -> None:
    """Opportunistic session-boundary distillation: promote durable entries."""

    distill_durable_entries(project_id, root=root, scope=scope)
