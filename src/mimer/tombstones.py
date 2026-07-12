"""Tombstones (ADR 0012): the durable record of a forgotten fact's identity.

A soft "forget" removes a fact from the curated layers and writes a tombstone so
distillation never re-promotes it and recall never surfaces it — while the
append-only long-term record stays untouched. Stored as an append-only JSONL
file at the store root, so tombstones survive a reindex.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from mimer.matcher import is_same_fact
from mimer.paths import store_root
from mimer.storeio import append_text

TOMBSTONES_FILENAME = "tombstones.jsonl"


def tombstones_path(root: Path | None = None) -> Path:
    """Path to the store's tombstone ledger."""

    return (root or store_root()) / TOMBSTONES_FILENAME


def write_tombstone(
    text: str, *, project_id: str, root: Path | None = None, tier: str = "forget"
) -> None:
    """Append a tombstone recording a forgotten fact's identity and origin.

    The forgotten fact is stored verbatim; identity against it is decided by the
    shared matcher (:func:`mimer.matcher.is_same_fact`), not a pre-normalised key.
    """

    record = {
        "text": text,
        "project_id": project_id,
        "tier": tier,
        "at": datetime.now(UTC).isoformat(),
    }
    append_text(tombstones_path(root), json.dumps(record, ensure_ascii=False))


def load_tombstones(root: Path | None = None) -> list[dict[str, str]]:
    """Load every tombstone record; an absent ledger yields an empty list."""

    path = tombstones_path(root)
    if not path.exists():
        return []

    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def is_tombstoned(text: str, *, project_id: str, root: Path | None = None) -> bool:
    """Whether a fact has been forgotten in the given project.

    A reworded restatement of a forgotten fact still counts as forgotten, because
    identity is decided by the shared matcher rather than exact string equality.
    """

    return any(
        record.get("project_id") == project_id and is_same_fact(text, record["text"])
        for record in load_tombstones(root)
    )
