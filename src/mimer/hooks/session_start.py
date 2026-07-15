"""SessionStart hook entry point (Stage 1).

Resolves the project for the session's working directory and injects the
snapshot — short-term memory only at this stage; the profile and manifest join
in later tickets. Injection happens on every SessionStart source, re-injecting
deliberately on ``compact`` so a compacted context never loses its memory
(ADR 0016), and it is announced, never silent (ADR 0014).
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from mimer import clock
from mimer.bundle import concept_headlines, render_profile
from mimer.distill import announcements
from mimer.failure_log import fresh_failures
from mimer.hooks.runner import run_hook
from mimer.leakage import pending_consent_requests
from mimer.manifest import long_term_manifest
from mimer.native_memory import is_native_memory_enabled
from mimer.paths import store_root
from mimer.pause import is_paused
from mimer.project import confirm_hint, resolve
from mimer.registry import Registry
from mimer.shortterm import ensure_short_term, read_short_term
from mimer.snapshot import DATA_FRAME_HEADER, build_snapshot


def handle(payload: Mapping[str, Any]) -> None:
    """Resolve the project and inject its snapshot as additional context."""

    root = store_root()
    cwd = Path(payload.get("cwd") or ".")
    source = str(payload.get("source") or "startup")

    # Resolve the project; an identity that needs confirmation injects nothing
    # but says so, rather than binding memory to an unconfirmed directory.
    resolution = resolve(cwd, root=root)
    if resolution.project_id is None:
        _emit(
            f"{DATA_FRAME_HEADER}\n\nMimer: this directory's project identity needs "
            f"confirmation; no memory was injected. {confirm_hint(resolution.candidate_id)}"
        )
        return

    # Ensure the short-term file exists, then inject its framed, aged snapshot,
    # the pinned profile, and the manifest (long-term coverage + Concept headlines).
    ensure_short_term(resolution.project_id, root)
    short_term_text = read_short_term(resolution.project_id, root)

    # Build and emit the snapshot inside the announcement-queue context manager: it
    # yields the queued titles and clears exactly those only on a clean exit, so a
    # failure here re-announces next session rather than dropping the notice
    # (at-least-once, ADR 0014, #40).
    with announcements(resolution.project_id, root) as distilled:
        snapshot = build_snapshot(
            resolution.project_id,
            short_term_text,
            today=clock.today(),
            source=source,
            manifest=_manifest(resolution.project_id, root),
            profile=render_profile(root),
            distilled=distilled,
            consent=pending_consent_requests(resolution.project_id, root),
            health=_health_notice(root),
            paused=_pause_notice(root),
            capture_off=_capture_notice(resolution.project_id, root),
            native_warning=_native_memory_notice(cwd),
        )
        _emit(snapshot)


def _native_memory_notice(cwd: Path) -> str:
    """A one-line warning while Claude Code's native auto memory is on here (ADR 0025).

    Keyed off the session's own working directory — where ``.claude/settings.json``
    lives — so an absent file or an absent key (both the default-on state) still
    warn. It is a warning, not a mild notice: Mimer replaces native memory rather
    than racing it, because a fact forgotten or redacted in Mimer can be silently
    re-injected by the native one. Mimer never flips the switch itself; the warning
    only points at the command that does, on the user's own request (#68).
    """

    if not is_native_memory_enabled(cwd):
        return ""
    return (
        "⚠ Mimer: Claude Code's native auto memory is ON for this project — a fact you "
        "forget or redact in Mimer can be silently re-injected by it. Run "
        '"mimer-manage disable-native-memory" to switch it off here; Mimer never flips it '
        "for you."
    )


def _pause_notice(root: Path) -> str:
    """A one-line notice when a store-wide capture pause is in effect (#35).

    Announcing a standing pause every session is what keeps a forgotten or
    crash-stranded pause from silently swallowing later sessions' memory.
    """

    if not is_paused(root):
        return ""
    return (
        "⏸ Mimer: capture is PAUSED store-wide — nothing is being recorded this "
        'session. Say "resume capture" to lift it.'
    )


def _capture_notice(project_id: str, root: Path) -> str:
    """A one-line notice when this project's per-project capture is off (#35).

    A per-project ``capture off`` is a standing, indefinite suppression just like
    a pause; announcing it every session — for parity with the pause notice —
    keeps a forgotten one from silently swallowing this project's memory.
    """

    if Registry.load(root).capture_enabled(project_id):
        return ""
    return (
        "⏹ Mimer: capture is OFF for this project — nothing is being recorded here. "
        'Say "turn capture on" to re-enable it.'
    )


def _health_notice(root: Path) -> str:
    """A one-line notice when the failure log has fresh entries (ADR 0011)."""

    failures = fresh_failures(root)
    if not failures:
        return ""
    return f"⚠ Mimer health: {len(failures)} recent failure(s) logged — see mimer.log."


def _manifest(project_id: str, root: Path) -> str:
    """The memory manifest: long-term coverage plus visible Concept headlines."""

    manifest = long_term_manifest(project_id, root)
    headlines = concept_headlines(root, project_id=project_id)
    if headlines:
        joined = "; ".join(headlines)
        manifest += f"\nPermanent memory: {len(headlines)} concept(s) — {joined}"
    return manifest


def _emit(additional_context: str) -> None:
    """Write the SessionStart context-injection payload to stdout."""

    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": additional_context,
        }
    }
    sys.stdout.write(json.dumps(output))


def main() -> int:
    """Console entry point for the SessionStart hook."""

    return run_hook("SessionStart", handle)


if __name__ == "__main__":
    raise SystemExit(main())
