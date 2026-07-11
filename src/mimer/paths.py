"""Store-location primitives: where Mimer keeps its files, overridable for tests
and for the packaged install (#16). No I/O happens here — only path resolution.
"""

from __future__ import annotations

import os
from pathlib import Path

# Environment variable that relocates the entire store. Tests set it so the real
# ``~/.mimer`` is never touched; in production it is left unset.
STORE_ROOT_ENV = "MIMER_HOME"

# Fixed filenames inside the store root.
CONFIG_FILENAME = "config.toml"
LOG_FILENAME = "mimer.log"


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
