"""Store-location primitives: where Mimer keeps its files, overridable for tests
and for the packaged install (#16). No I/O happens here — only path resolution.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

# Environment variable that relocates the entire store. Tests set it so the real
# ``~/.mimer`` is never touched; in production it is left unset.
STORE_ROOT_ENV = "MIMER_HOME"

# Fixed filenames inside the store root.
CONFIG_FILENAME = "config.toml"
LOG_FILENAME = "mimer.log"

# A bare, path-safe identifier: lowercase alphanumerics in hyphen-separated
# groups, with no leading, trailing or doubled hyphen — and, crucially, no
# slash, dot, or other separator that could escape a directory. Concept slugs
# and session ids are validated against this before they become a store path.
_IDENTIFIER_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def store_root() -> Path:
    """Resolve the store root, honouring the ``MIMER_HOME`` override.

    The returned path is not guaranteed to exist — creating it is the job of
    :func:`mimer.store.ensure_store`. Defaults to ``~/.mimer`` when the override
    is unset or empty.
    """

    override = os.environ.get(STORE_ROOT_ENV)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".mimer"


def safe_identifier(value: str, *, kind: str = "identifier") -> str:
    """Return ``value`` if it is a bare, path-safe identifier; raise otherwise.

    An identifier that becomes a filename — a Concept slug, a session id — must
    not carry a slash or ``..`` that would let an attacker-directed value resolve
    outside the store and have Mimer read or unlink an arbitrary file (#25).
    Validating here, the chokepoint every path-building helper funnels through,
    protects every caller rather than one entry point.

    Args:
        value: The candidate identifier.
        kind: What the identifier names, used only to phrase the error.

    Returns:
        ``value`` unchanged when it is a bare slug.

    Raises:
        ValueError: when ``value`` is not lowercase alphanumerics and hyphens.
    """

    if not _IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"invalid {kind}: {value!r} is not a bare, path-safe identifier")
    return value
