"""The store walk: the read-only enumeration of what the store holds on disk —
project ids (on disk, or known to the registry) and the dates a project's
long-term memory covers. The one module that walks the projects tree; no other
module lists its directories.

It sits above the registry and long-term modules in the import graph — the
union needs the :class:`~mimer.registry.Registry` — so nothing below them may
import it. It reuses their existing layout constants and helpers rather than
duplicating where the store keeps its files. It is entirely read-only: no
writes, no locks, wholly outside ADR 0011's write discipline.
"""

from __future__ import annotations

from pathlib import Path

from mimer.longterm import long_term_dir
from mimer.paths import store_root
from mimer.registry import PROJECTS_DIRNAME, Registry

# A day of long-term memory is one ``<YYYY-MM-DD>.md`` file. Filtering on this
# suffix keeps the enumeration to the daily logs and excludes the dedup ledgers
# that share the long-term directory (dotfiles with no ``.md`` suffix).
DAILY_LOG_SUFFIX = ".md"


def disk_project_ids(root: Path | None = None) -> list[str]:
    """Project ids present on disk, sorted; ``[]`` when the projects directory is
    absent.

    A project id is the name of a subdirectory of the store's ``projects/``
    directory. Stray non-directory entries there are skipped, so only real
    project directories count.

    Args:
        root: Store root to walk; defaults to :func:`mimer.paths.store_root`.

    Returns:
        The sorted on-disk project ids.
    """

    # An absent projects directory — a fresh store, or one that has never bound a
    # project — is an empty enumeration, not an error.
    projects = (root or store_root()) / PROJECTS_DIRNAME
    if not projects.is_dir():
        return []

    # The project ids are the subdirectory names; a stray file is not one.
    return sorted(entry.name for entry in projects.iterdir() if entry.is_dir())


def known_project_ids(root: Path | None = None) -> list[str]:
    """Every project the store knows of — the registry's ids unioned with those on
    disk — sorted.

    A registered project whose directory does not exist yet, and a disk-only
    orphan never entered in the registry, both count: the union is the complete
    set of project ids the store is aware of.

    Args:
        root: Store root to walk; defaults to :func:`mimer.paths.store_root`.

    Returns:
        The sorted union of registered and on-disk project ids.
    """

    # Union the registry against the disk so neither a registry-only project nor a
    # disk-only orphan is missed.
    registered = Registry.load(root).project_ids()
    return sorted(set(registered) | set(disk_project_ids(root)))


def daily_log_days(project_id: str, root: Path | None = None) -> list[str]:
    """The ``YYYY-MM-DD`` stems of a project's long-term memory, sorted; ``[]``
    when it has none.

    Each covered day is one ``<day>.md`` file in the project's long-term
    directory. A project never captured to — no long-term directory — covers no
    days. The stems are ISO dates, so their lexical order is chronological order.

    Args:
        project_id: The project whose long-term coverage to enumerate.
        root: Store root to walk; defaults to :func:`mimer.paths.store_root`.

    Returns:
        The sorted covered days.
    """

    # A project with no long-term directory covers no days.
    directory = long_term_dir(project_id, root)
    if not directory.is_dir():
        return []

    # The covered days are the daily-log stems; the dedup ledgers alongside them
    # are not ``.md`` files and so are excluded.
    return sorted(entry.stem for entry in directory.iterdir() if entry.suffix == DAILY_LOG_SUFFIX)
