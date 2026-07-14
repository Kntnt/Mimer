"""The re-entrancy guard (ADR 0009): a marker environment variable Mimer sets on
every Claude session it spawns, so a spawned session can never trigger Mimer's
own hooks and capture itself.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

# Env var set on spawned Claude invocations; any Mimer hook that sees it exits at
# once, before touching the store.
GUARD_ENV = "MIMER_GUARD"


def is_guarded() -> bool:
    """True when the current process is running under the re-entrancy guard."""

    return bool(os.environ.get(GUARD_ENV))


def spawn_env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return an environment carrying the guard marker, for spawning a Claude
    call (used by the session-boundary pass, #7).

    Args:
        base: Environment to extend; defaults to the current ``os.environ``.
    """

    env = dict(base if base is not None else os.environ)
    env[GUARD_ENV] = "1"
    return env
