"""Bootstrap of the on-disk store: an owner-only directory holding, at this
stage, the configuration file and the failure log. Idempotent by design so any
hook may call it on every invocation.
"""

from __future__ import annotations

from pathlib import Path

from mimer.paths import CONFIG_FILENAME, LOG_FILENAME, store_root

# Owner-only permission bits. The store concentrates every project's material in
# one place and must stay unreadable to other users (the vision's trust boundary,
# ADR 0013).
DIR_MODE = 0o700
FILE_MODE = 0o600

# The configuration file seeded on first run: hand-editable and extended by later
# stages. Deliberately minimal — its full surface is an open decision in the
# vision.
DEFAULT_CONFIG = """\
# Mimer configuration. Created on first run; safe to edit by hand.

[core]
# Schema version of this configuration file.
version = 1
"""


def ensure_store(root: Path | None = None) -> Path:
    """Create the store root, configuration file and failure log if absent.

    The directory mode is pinned to 0700 and the files to 0600 on every call, so
    a store created under a permissive umask is corrected in place. Existing
    files are never overwritten, so a hand-edited config and prior failure-log
    lines survive.

    Args:
        root: Store root to create; defaults to :func:`mimer.paths.store_root`.

    Returns:
        The store root path.
    """

    root = root or store_root()

    # Create the root with owner-only access, correcting the mode even when it
    # pre-existed under a looser umask.
    root.mkdir(mode=DIR_MODE, parents=True, exist_ok=True)
    root.chmod(DIR_MODE)

    # Seed the configuration file once, then pin its mode.
    config = root / CONFIG_FILENAME
    if not config.exists():
        config.write_text(DEFAULT_CONFIG, encoding="utf-8")
    config.chmod(FILE_MODE)

    # Seed an empty failure log once, then pin its mode.
    log = root / LOG_FILENAME
    if not log.exists():
        log.touch()
    log.chmod(FILE_MODE)

    return root
