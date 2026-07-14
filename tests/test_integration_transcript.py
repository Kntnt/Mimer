"""Transcript-adapter coverage against a real (redacted) Claude Code transcript.

The unit tests in ``test_transcript.py`` drive hand-written fixtures shaped to
exactly what the adapter parses. This module pins the adapter to the *true*
on-disk JSONL format captured from an actual Claude Code session and redacted:
every structural field and record type is faithful to the live format, only the
human- and tool-generated content is replaced. A vendor-side field rename or a
newly introduced record type therefore surfaces here as a red build rather than
silently breaking capture.
"""

from __future__ import annotations

from pathlib import Path

from mimer.transcript import last_exchange

# The redacted real transcript. Its records cover every construct the live format
# throws at the adapter: a plain-string user prompt, assistant messages whose
# content mixes thinking/text/tool_use blocks, a tool_result-only user turn, and
# the foreign record types (queue-operation, attachment, system, last-prompt,
# ai-title) that are neither user nor assistant.
REAL_TRANSCRIPT = Path(__file__).resolve().parent / "fixtures" / "real_transcript.jsonl"

# The one real user prompt and the final assistant answer in the fixture.
USER_PROMPT = "What indexing approach should we use for recall?"
FINAL_ANSWER = "Use sqlite-vec: it is a single-file store that needs no server."


def test_last_exchange_from_real_transcript_skips_noise_and_tool_records() -> None:
    """The final real user prompt and assistant answer are extracted from the true
    format, past thinking/tool_use blocks, the tool_result-only user turn and the
    foreign record types that surround them."""

    exchange = last_exchange(REAL_TRANSCRIPT)

    assert exchange is not None
    assert exchange.user_text == USER_PROMPT
    assert exchange.assistant_text == FINAL_ANSWER
    assert exchange.date == "2026-06-18"
