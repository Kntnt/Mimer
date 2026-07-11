"""The common hook runner shared by every Mimer hook: enforce the re-entrancy
guard first, then bootstrap-the-store-and-dispatch with every failure caught and
logged. A Mimer hook never crashes the session it fires in.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Mapping
from typing import Any

from mimer.failure_log import log_failure
from mimer.guard import is_guarded
from mimer.paths import store_root
from mimer.store import ensure_store

# A hook handler receives the parsed JSON payload and performs its side effects.
HookHandler = Callable[[Mapping[str, Any]], None]


def run_hook(event_name: str, handler: HookHandler) -> int:
    """Run one hook: enforce the guard, bootstrap the store, dispatch, absorb.

    Args:
        event_name: The Claude Code event name, used to label logged failures.
        handler: The event-specific behaviour, given the parsed payload.

    Returns:
        A process exit code — always 0. A detached hook reports problems to the
        failure log, never through a non-zero exit that would surface to the
        user mid-session.
    """

    # Re-entrancy guard: exit before any store access, so a Mimer-spawned session
    # leaves the store untouched (ADR 0009).
    if is_guarded():
        return 0

    # Bootstrap and dispatch; any failure is logged rather than raised, so the
    # session is never disturbed while the problem stays observable.
    try:
        ensure_store()
        payload = _read_payload()
        handler(payload)
    except Exception as exc:  # noqa: BLE001 - a hook must never crash the session
        log_failure(f"{event_name}: {exc!r}", root=store_root())

    return 0


def _read_payload() -> Mapping[str, Any]:
    """Parse the hook's JSON stdin payload.

    Empty or whitespace-only stdin yields an empty mapping (a benign no-payload
    invocation). Malformed non-empty input raises, which the caller treats as a
    logged failure.
    """

    raw = sys.stdin.read()
    if not raw.strip():
        return {}

    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise TypeError(f"expected a JSON object payload, got {type(parsed).__name__}")
    return parsed
