"""Rendering the snapshot injected at session start (ADRs 0014, 0016).

The snapshot wraps short-term memory in a data frame carrying the standing rule
that memory is information, not instructions; prepends a one-line announcement of
what was injected; and labels every dated entry with its age, so a three-week-old
pending decision reads as three weeks old rather than as current truth. The whole
payload is enclosed in a per-injection nonce fence (``mimer.framing``) so stored
content cannot reproduce or escape the frame.
"""

from __future__ import annotations

import re
from datetime import date

from mimer.framing import DATA_FRAME_HEADER, frame

__all__ = [
    "DATA_FRAME_HEADER",
    "annotate_ages",
    "build_snapshot",
    "count_dated_items",
]

# Matches a leading date stamp such as ``[2026-07-11]``.
_DATE_TOKEN_RE = re.compile(r"\[(\d{4})-(\d{2})-(\d{2})\]")


def _age_label(entry_date: date, today: date) -> str:
    """A human age for a dated entry relative to ``today``."""

    days = (today - entry_date).days
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    return f"{days} days ago"


def annotate_ages(text: str, today: date) -> str:
    """Append an age label after every ``[YYYY-MM-DD]`` token in ``text``."""

    def replace(match: re.Match[str]) -> str:
        year, month, day = (int(part) for part in match.groups())
        label = _age_label(date(year, month, day), today)
        return f"{match.group(0)} ({label})"

    return _DATE_TOKEN_RE.sub(replace, text)


def count_dated_items(text: str) -> int:
    """Count the dated entries in a short-term memory body."""

    return len(_DATE_TOKEN_RE.findall(text))


def build_snapshot(
    project_id: str,
    short_term_text: str,
    *,
    today: date,
    source: str,
    manifest: str = "",
    profile: str = "",
    distilled: list[str] | None = None,
    consent: list[str] | None = None,
    health: str = "",
    paused: str = "",
    capture_off: str = "",
    native_warning: str = "",
) -> str:
    """Render the full injection payload for a project's short-term memory.

    Args:
        project_id: The resolved project id.
        short_term_text: The raw short-term memory Markdown.
        today: The reference date for age labels.
        source: The SessionStart source (``startup``/``compact``/…), named in the
            announcement so a re-injection is visible.
        manifest: A compact statement of what memory holds beyond the snapshot.
        profile: The pinned profile Concepts, injected on every session.
        distilled: The titles promoted since the last session, announced so a new
            global Concept is visible and its promotion reversible (ADR 0014).
        consent: The sensitive facts held at project scope awaiting the user's
            consent to go global; re-posed every session until answered (ADR 0027).
        health: A one-line health warning when the failure log is fresh.
        paused: A one-line notice when a store-wide capture pause is in effect, so
            a standing pause is announced every session rather than silent (#35).
        capture_off: A one-line notice when this project's per-project capture is
            switched off, so a standing per-project suppression is announced every
            session rather than silent, for parity with the pause notice (#35).
        native_warning: A one-line warning when Claude Code's native auto memory is
            on for this project — a warning, not a mild notice, because a fact
            forgotten in Mimer can otherwise be re-injected by it (ADR 0025, #68).
    """

    count = count_dated_items(short_term_text)

    # The one-line announcement makes injection visible, never silent (ADR 0014).
    if count == 0:
        announcement = (
            f'Mimer: no short-term memory yet for project "{project_id}" (source: {source}).'
        )
    else:
        announcement = (
            f'Mimer: injected short-term memory for project "{project_id}" '
            f"({count} dated item(s); source: {source})."
        )

    # The manifest tells the agent what memory holds beyond the snapshot, so it
    # knows when recall is worth invoking; the distilled line announces what was
    # promoted since the last session (ADR 0014).
    lines = []
    if paused:
        lines.append(paused)
    if capture_off:
        lines.append(capture_off)
    if health:
        lines.append(health)
    if native_warning:
        lines.append(native_warning)
    lines.append(announcement)
    if manifest:
        lines.append(manifest)
    if distilled:
        lines.append(f"Distilled since last session: {'; '.join(distilled)}.")

    # The consent line is the leakage guard's ask: these sensitive facts are held
    # at project scope and go global only if you consent — re-posed until answered,
    # so it is separate from the one-time distilled announcement (ADR 0027).
    if consent:
        lines.append(
            "Mimer: awaiting your consent to promote these sensitive fact(s) to "
            f"global scope (held at project scope until then): {'; '.join(consent)}."
        )
    preamble = "\n".join(lines)

    # Fence the whole payload — the announcement, the pinned profile and the
    # aged short-term body are all content-derived, so all sit inside the frame
    # (ADR 0014). The nonce fence is what stored content cannot forge.
    body = annotate_ages(short_term_text, today)
    sections = [preamble]
    if profile:
        sections.append(profile)
    sections.append(body)
    return frame("\n\n".join(sections))
