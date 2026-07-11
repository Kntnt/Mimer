"""A version-tolerant adapter over Claude Code session transcripts.

The transcript JSONL format is vendor-internal and changes between releases, so
this adapter is deliberately forgiving: it skips lines it cannot parse, accepts
message content as either a string or a list of blocks, and derives a stable
turn identity from the exchange's content (for capture idempotency) rather than
from any vendor id.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path


@dataclass(frozen=True)
class Exchange:
    """The last user/assistant exchange extracted from a transcript."""

    user_text: str
    assistant_text: str
    timestamp: str
    turn_id: str

    @property
    def date(self) -> str:
        """The day the turn belongs to (its timestamp's date), ``YYYY-MM-DD``."""

        return _parse_date(self.timestamp).isoformat()

    @property
    def time_label(self) -> str:
        """The turn's wall-clock ``HH:MM``, or ``??:??`` when unknown."""

        moment = _parse_datetime(self.timestamp)
        return moment.strftime("%H:%M") if moment else "??:??"


def last_exchange(transcript_path: Path) -> Exchange | None:
    """Extract the final user/assistant exchange from a transcript, or None.

    Raises if the transcript path cannot be read; unparseable individual lines
    are skipped so a partially-corrupt transcript still yields its last exchange.
    """

    messages = _parse_messages(transcript_path.read_text(encoding="utf-8"))

    # The last assistant message with text, and the last user message before it.
    assistant_index = next(
        (
            i
            for i in range(len(messages) - 1, -1, -1)
            if messages[i][0] == "assistant" and messages[i][1]
        ),
        None,
    )
    if assistant_index is None:
        return None
    user_index = next(
        (
            i
            for i in range(assistant_index - 1, -1, -1)
            if messages[i][0] == "user" and messages[i][1]
        ),
        None,
    )

    _, assistant_text, timestamp = messages[assistant_index]
    user_text = messages[user_index][1] if user_index is not None else ""
    turn_id = hashlib.sha256(f"{user_text}\x00{assistant_text}".encode()).hexdigest()[:16]
    return Exchange(user_text, assistant_text, timestamp, turn_id)


def _parse_messages(raw: str) -> list[tuple[str, str, str]]:
    """Parse a transcript into ``(role, text, timestamp)`` tuples, skipping junk."""

    messages: list[tuple[str, str, str]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue

        role = _role(record)
        if role is None:
            continue
        messages.append((role, _text(record), str(record.get("timestamp", ""))))

    return messages


def _role(record: dict[str, object]) -> str | None:
    """Determine the message role, tolerating either ``type`` or nested ``role``."""

    kind = record.get("type")
    if kind in ("user", "assistant"):
        return str(kind)
    message = record.get("message")
    if isinstance(message, dict) and message.get("role") in ("user", "assistant"):
        return str(message["role"])
    return None


def _text(record: dict[str, object]) -> str:
    """Extract the plain text of a message, from a string or a block list."""

    message = record.get("message")
    content: object = message.get("content") if isinstance(message, dict) else record.get("content")

    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [
            block["text"]
            for block in content
            if isinstance(block, dict)
            and block.get("type") == "text"
            and isinstance(block.get("text"), str)
        ]
        return " ".join(parts).strip()
    return ""


def _parse_datetime(timestamp: str) -> datetime | None:
    """Best-effort parse of an ISO-8601 timestamp (``Z`` suffix tolerated)."""

    try:
        return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_date(timestamp: str) -> date:
    """The date of a timestamp, falling back to today when unparseable."""

    moment = _parse_datetime(timestamp)
    return moment.date() if moment else datetime.now(UTC).date()
