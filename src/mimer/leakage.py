"""The leakage guard (ADR 0027): sensitive facts wait for consent before going
global.

Distillation promotes a client-neutral fact to global scope automatically, but a
fact the judgment rules classify as **sensitive** — one carrying a clear
confidentiality signal — must never travel across projects on the model's judgment
alone. This module is the guard at that moment: it answers *is this sensitive?*
(:func:`is_sensitive`) and holds the per-project queue of **consent requests**
raised when a sensitive fact is held back. The hold itself — creating the Concept
at project scope instead of global — lives in :mod:`mimer.distill`, which routes
its promote-to-global decision through this seam.

The classifier is a deliberately tight default: an explicit confidentiality or
non-disclosure signal, not mere client-relatedness, so consent prompts stay rare
(set-and-forget). It is the code-level seam the memory skill's editable judgment
rules (ADR 0018) will drive with their own wording; the final rule text lands with
the skill reconciliation (#70), so the default here stays minimal and unambiguous.

Unlike the announcement queue (:mod:`mimer.distill`), the consent queue is never
cleared on emit: a consent request is re-posed at every session start until the
user actually answers it, so the fact waits — project-bound, never global —
until then. The safe state is the waiting state. It clears only on *resolution* —
when the user promotes the held fact to global, :func:`resolve_consent_request`
drops that answered request so its now-stale prompt stops re-posing (#69). The
inverse hold-then-widen mutation is :func:`mimer.bundle.promote_to_global`, which
carries out that clear as part of the consent "yes".
"""

from __future__ import annotations

import re
from pathlib import Path

from mimer.paths import store_root
from mimer.registry import project_dir
from mimer.storeio import append_text, project_lock, write_atomic

# The on-disk per-project consent queue: the sensitive facts held at project scope
# whose promotion to global awaits the user's consent, one request per line.
CONSENT_QUEUE_FILENAME = ".consent-queue"

# The tight default sensitivity signal: an explicit confidentiality or
# non-disclosure marker. ``confidential`` matches its family (``confidentiality``,
# ``confidentially``); ``nda`` is matched on a word boundary so ``agenda`` and
# ``mandatory`` never trip it. Obvious secrets (keys, passwords, tokens) are
# already stripped by the redaction pass before storage, so the guard's remaining
# job is the softer "explicitly confidential" case, not secret detection.
_SENSITIVITY_RE = re.compile(r"\bconfidential\w*\b|\bnda\b|\bnon-disclosure\b", re.IGNORECASE)


def is_sensitive(text: str) -> bool:
    """Whether ``text`` carries a clear confidentiality signal (ADR 0027).

    The default classifier the leakage guard drives, and the seam the editable
    judgment rules (ADR 0018) refine. Tight by design — the axis is "is this
    confidential?", not "is this about a client?" — so a bare client name or email
    is not sensitive, keeping the consent prompt a rare, set-and-forget event.
    """

    return _SENSITIVITY_RE.search(text) is not None


def consent_queue_path(project_id: str, root: Path | None = None) -> Path:
    """The path to a project's consent queue file."""

    return project_dir(project_id, root or store_root()) / CONSENT_QUEUE_FILENAME


def queue_consent_request(project_id: str, request: str, root: Path | None = None) -> None:
    """Queue a consent request for a sensitive fact held at project scope.

    A lockless ``O_APPEND`` write, like every other queue enqueue (ADR 0011). It
    stays lockless despite :func:`resolve_consent_request`'s locked clear only
    because every enqueue runs under the caller's project lock — the boundary pass's
    :func:`mimer.shortterm.rewrite_sections` — so a request appended concurrently
    cannot be lost in that clear's read-then-write window, exactly as the
    announcement queue's under-lock enqueue invariant holds (#40, #69). Any
    duplicate is collapsed at read time by :func:`pending_consent_requests`.
    """

    append_text(consent_queue_path(project_id, root), request)


def pending_consent_requests(project_id: str, root: Path | None = None) -> list[str]:
    """The sensitive facts awaiting the user's consent to go global, for this
    project — deduplicated, in the order they were first queued.

    A pure read that never clears the queue: the consent question persists until it
    is answered, so this returns the same requests session after session (ADR 0027).
    Deduplication here lets the enqueue stay a plain lockless append while a fact
    held more than once is still asked about only once.
    """

    path = consent_queue_path(project_id, root)
    if not path.exists():
        return []

    # Read every queued request, dropping blank lines and any later repeat so the
    # same held fact is surfaced once even if it was queued more than once.
    seen: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and stripped not in seen:
            seen.append(stripped)
    return seen


def resolve_consent_request(project_id: str, request: str, root: Path | None = None) -> None:
    """Clear an answered consent request from a project's queue: the consent "yes".

    The queue is never cleared on *emit* — a request is re-posed at every session
    start until answered (:func:`pending_consent_requests`) — but it must be cleared
    on *resolution*, when the user promotes the held fact to global
    (:func:`mimer.bundle.promote_to_global`). Without that clear, a fact already
    widened to global keeps firing its now-stale "awaiting your consent" prompt every
    session, forever (#69). This drops exactly the answered request — every line equal
    to it — and leaves any other held fact's request in place; a request never queued
    (the attended "distill now" path defers nothing) is a silent no-op.

    The re-read and rewrite run under the project lock so this read-modify-write
    cannot clobber a concurrent distiller's consent enqueue: that enqueue appends
    while holding the same project lock (the boundary pass's
    :func:`mimer.shortterm.rewrite_sections`), so it and this clear serialise — the
    survivors written atomically, the file removed when none remain — exactly as the
    announcement queue's locked clear does (ADR 0011, #40).
    """

    path = consent_queue_path(project_id, root)
    target = request.strip()

    # Re-read the live queue under the lock, drop every line equal to the answered
    # request, and write back the remainder; a request queued concurrently for a
    # different held fact is not equal to target, so it survives to the next session.
    with project_lock(project_id, root=root):
        if not path.exists():
            return
        remaining = [
            line
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and line.strip() != target
        ]
        if remaining:
            write_atomic(path, "\n".join(remaining) + "\n")
        else:
            path.unlink(missing_ok=True)
