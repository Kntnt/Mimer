"""Build Claude Code transcript JSONL fixtures for capture tests.

The real transcript format is vendor-internal; these fixtures follow the shape
Mimer's version-tolerant adapter parses (a ``type`` field, ``message.content``
as a string or a list of blocks, a ``timestamp``). Fidelity to the live format
is checked in the end-to-end verification, not here.
"""

from __future__ import annotations

import json
from pathlib import Path


def _user_line(text: str, timestamp: str, index: int) -> dict[str, object]:
    return {
        "type": "user",
        "uuid": f"user-{index}",
        "timestamp": timestamp,
        "message": {"role": "user", "content": text},
    }


def _assistant_line(text: str, timestamp: str, index: int) -> dict[str, object]:
    return {
        "type": "assistant",
        "uuid": f"assistant-{index}",
        "timestamp": timestamp,
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
    }


def write_transcript(path: Path, turns: list[tuple[str, str, str]]) -> Path:
    """Write a transcript JSONL of ``(user, assistant, timestamp)`` turns."""

    lines: list[dict[str, object]] = []
    for index, (user, assistant, timestamp) in enumerate(turns):
        lines.append(_user_line(user, timestamp, index))
        lines.append(_assistant_line(assistant, timestamp, index))

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")
    return path
