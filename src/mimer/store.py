"""Bootstrap of the on-disk store: an owner-only directory holding, at this
stage, the failure log. Idempotent by design so any hook may call it on every
invocation.
"""

from __future__ import annotations

from pathlib import Path

from mimer.paths import LOG_FILENAME, store_root

# Owner-only permission bits. The store concentrates every project's material in
# one place and must stay unreadable to other users (the vision's trust boundary,
# ADR 0013).
DIR_MODE = 0o700
FILE_MODE = 0o600


def ensure_store(root: Path | None = None) -> Path:
    """Create the store root and failure log if absent.

    The directory mode is pinned to 0700 and the files to 0600 on every call, so
    a store created under a permissive umask is corrected in place. Existing
    files are never overwritten, so prior failure-log lines survive. Per-project
    settings live in the registry, not a config file, so none is seeded (#35).

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

    # Seed an empty failure log once, owner-only from creation; re-pin every call
    # to correct a log an older store left world-readable.
    log = root / LOG_FILENAME
    if not log.exists():
        log.touch(mode=FILE_MODE)
    log.chmod(FILE_MODE)

    return root


def heal_permissions(root: Path | None = None) -> None:
    """Re-pin every existing file and directory under the store to owner-only.

    :func:`ensure_store` and :func:`ensure_dir` pin only what they create, so a
    store first written by a version predating the owner-only invariant keeps its
    subdirectories world-traversable (0755) and any pre-fix files world-readable
    forever — the 0700 root masks this only until the store is synced or backed up
    without that mode (ADR 0013, issue #26). This sweep, run at install/upgrade,
    corrects the whole tree in place: the migration that reaches what per-write
    pinning cannot, since directories are never rewritten. Idempotent and a no-op
    when the store does not yet exist.

    Args:
        root: Store root to heal; defaults to :func:`mimer.paths.store_root`.
    """

    root = root or store_root()
    if not root.exists():
        return

    # Pin the root, then every descendant: directories to 0700 and files to 0600,
    # so the invariant holds on its own rather than only via the root's mode.
    root.chmod(DIR_MODE)
    for path in root.rglob("*"):
        # Skip a path a concurrent writer removed between rglob yielding it and
        # this chmod — a detached capture consuming a spool file, or a write_atomic
        # temp being os.replace'd — so a live store never fails the install sweep.
        try:
            path.chmod(DIR_MODE if path.is_dir() else FILE_MODE)
        except FileNotFoundError:
            continue


def ensure_dir(directory: Path) -> None:
    """Create ``directory`` and any missing ancestors, each pinned to 0700.

    ``Path.mkdir(mode=…, parents=True)`` applies the mode only to the final
    component and creates intermediate parents at the umask default (typically
    0755, world-traversable). The store concentrates every project's memory, so
    no directory Mimer creates may be readable by other users (ADR 0013); this
    helper creates and chmods every missing level down to ``directory`` to
    :data:`DIR_MODE`. Only what the call creates is pinned — an existing ancestor
    (a temp directory, the user's home) is left untouched.

    Args:
        directory: The directory to ensure; its missing ancestors are created too.
    """

    # Collect the missing chain from the target up to the first existing ancestor.
    missing: list[Path] = []
    current = directory
    while not current.exists():
        missing.append(current)
        current = current.parent

    # Create each missing level owner-only, correcting the umask default that
    # mkdir would otherwise leave on the intermediate directories.
    for path in reversed(missing):
        path.mkdir(mode=DIR_MODE, exist_ok=True)
        path.chmod(DIR_MODE)
