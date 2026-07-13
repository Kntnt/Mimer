"""The one clock Mimer keeps time by (#37).

Capture keys a turn's day and time off its transcript timestamp; the digest that
closes a session, the age labels the snapshot stamps on every dated entry, and
recency reranking all need to know what "today" is. Deriving those from
different zones let a single non-UTC session split its records across two daily
logs and read back in a jumbled date order.

This module is the single source of that clock: everything is UTC. The day a
turn belongs to (``transcript`` converts its timestamp to this zone), the digest
that closes the session, and the ages shown next session therefore all agree,
whatever zone the user sits in.
"""

from __future__ import annotations

from datetime import UTC, date, datetime


def today() -> date:
    """The current date on Mimer's canonical clock (UTC)."""

    return datetime.now(UTC).date()
