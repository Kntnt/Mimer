"""Packaging and first run (Stage 8): the install flow and its checks.

Mimer runs from plain files with a uv-managed environment. On install it checks
the interpreter can load SQLite extensions (compiled out of some system
Pythons — fail loudly and early, not silently at index time), pre-fetches the
embedding model so the first session never stalls on a download, and creates the
store. Uninstall leaves the store in place with a pointer note; the coexistence
guidance for Claude Code's native auto memory lives in the README (ADR 0019).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import sqlite_vec

from mimer.embedding import MODEL_NAME, embed
from mimer.index import reindex
from mimer.paths import store_root
from mimer.store import ensure_store

UNINSTALL_POINTER_FILENAME = "MIMER-UNINSTALLED.md"


@dataclass(frozen=True)
class InstallReport:
    """The result of the install flow."""

    ok: bool
    messages: list[str]


def check_sqlite_extensions() -> str | None:
    """Verify the interpreter can load SQLite extensions; return a problem or None.

    Returns an actionable message when extension loading is unavailable (the
    `sqlite-vec` index cannot work without it), or None when all is well.
    """

    try:
        connection = sqlite3.connect(":memory:")
        connection.enable_load_extension(True)
        sqlite_vec.load(connection)
        connection.execute("SELECT vec_version()").fetchone()
        connection.close()
    except Exception as exc:  # noqa: BLE001 - any failure here means extensions are unusable
        return (
            "This Python cannot load SQLite extensions, which Mimer's search index "
            f"requires (sqlite-vec). Details: {exc}. Install a Python built with "
            "extension loading enabled (for example the uv-managed CPython, or "
            "Homebrew's python), then re-run the install."
        )
    return None


def prefetch_embedding_model() -> None:
    """Download and load the embedding model so no session stalls on it."""

    embed(["warm up the embedding model"])


def run_install(root: Path | None = None) -> InstallReport:
    """Run the install flow: create the store, check capabilities, pre-fetch.

    Every step that can fail on a fresh machine — an interpreter that cannot
    load SQLite extensions, a model download over a flaky network, an index
    build — is turned into an actionable :class:`InstallReport` rather than a raw
    traceback, so first run reads as "try again", not "broken". The store is
    created first and every step is idempotent, so a failed install leaves a
    resumable state: fix the cause and re-run.
    """

    root = root or store_root()
    ensure_store(root)

    # Fail early when the interpreter cannot load SQLite extensions — the
    # sqlite-vec index cannot work without them.
    problem = check_sqlite_extensions()
    if problem is not None:
        return InstallReport(False, [problem])

    # Pre-fetch the embedding model; a download failure (typically no network)
    # becomes a report, not a traceback, mirroring the SQLite check above.
    try:
        prefetch_embedding_model()
    except Exception as exc:  # noqa: BLE001 - any download failure should degrade to a report
        return InstallReport(
            False,
            [
                f"Could not fetch the embedding model '{MODEL_NAME}', which Mimer's search "
                f"needs. This usually means no network connection. Details: {exc}. Check your "
                "connection and re-run the install — nothing was lost, it resumes from here."
            ],
        )

    # Build the index up front so capture, digest, git and bootstrap writes are
    # indexed from the first session; a build failure becomes a report too.
    try:
        reindex(root)
    except Exception as exc:  # noqa: BLE001 - any index-build failure should degrade to a report
        return InstallReport(
            False,
            [
                f"Could not build the search index. Details: {exc}. Your memory store was left "
                f"in place at {root}; re-run the install to try building the index again."
            ],
        )

    return InstallReport(
        True,
        [f"Store ready at {root}; embedding model '{MODEL_NAME}' fetched; index built."],
    )


def write_uninstall_pointer(root: Path | None = None) -> Path:
    """Leave a pointer note in the store on uninstall; the store itself stays."""

    root = root or store_root()
    ensure_store(root)

    pointer = root / UNINSTALL_POINTER_FILENAME
    pointer.write_text(
        "# Mimer was uninstalled\n\n"
        "The Mimer plugin's hooks have been removed, but your memory store was "
        "left here on purpose — nothing was deleted. This directory holds your "
        "short-term, long-term and permanent memory. To resume, reinstall the "
        "Mimer plugin; to remove your memory entirely, delete this directory.\n",
        encoding="utf-8",
    )
    return pointer


def install_main() -> int:
    """``mimer-install`` entry point: first-run provisioning and checks."""

    report = run_install(store_root())
    for message in report.messages:
        print(f"Mimer: {message}")
    if not report.ok:
        print("Mimer: install could not complete — see the message above.")
        return 1
    return 0


def uninstall_main() -> int:
    """``mimer-uninstall`` entry point: leave a pointer, keep the store."""

    pointer = write_uninstall_pointer(store_root())
    print(
        "Mimer: remove the plugin in Claude Code to unregister its hooks. "
        f"Your memory store was left in place; see {pointer}."
    )
    return 0
