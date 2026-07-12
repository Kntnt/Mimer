"""Hard erasure of the raw record (ADR 0012, issue #31).

Redact is the one sanctioned mutation of the otherwise append-only daily
long-term logs and the unedited transcript archive. This module rewrites every
span that states a forgotten fact — in the logs and in the archived transcripts
— to a redaction marker, then rebuilds the derived index (when one exists) so the
purged content stops surfacing in recall. It also serves the case where a secret
slipped past the storage-time redaction pass and is sitting raw in the record.

Matching delegates to the one shared "same fact?" matcher (:mod:`mimer.matcher`),
so redact and forget agree on what "the fact" is, with one deliberate difference
of degree between the two artefacts:

* **Logs** are Markdown entries, so a reworded restatement whose words no longer
  quote the fact verbatim is still erased — its whole entry body is replaced.
* **Transcripts** are JSONL, where whole-line replacement would destroy the
  record's structure, so only verbatim spans are erased. A reworded restatement
  buried in a transcript is out of reach — the same word-form limitation the
  matcher documents, and the reason the honest residual is stated to the user.

The residual is honest and non-negotiable: content exported or backed up before a
redact is beyond Mimer's reach.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from mimer.index import index_db_path, reindex
from mimer.longterm import long_term_dir, transcripts_dir
from mimer.matcher import is_same_fact
from mimer.paths import store_root
from mimer.redaction import REDACTED
from mimer.storeio import project_lock, write_atomic

# A bullet's leading structure — the ``-`` marker and an optional ``[date]`` — so
# a reworded entry can have its body replaced while its provenance prefix survives.
_ENTRY_PREFIX_RE = re.compile(r"^(\s*-\s*(?:\[[^\]]*\]\s*)?)(.*)$")


@dataclass(frozen=True)
class ErasureResult:
    """How much of the raw record one redact rewrote."""

    logs_rewritten: int
    transcripts_rewritten: int


def erase_from_raw_record(fact: str, *, project_id: str, root: Path | None = None) -> ErasureResult:
    """Erase ``fact`` from the project's daily logs and transcript archive, then
    reindex.

    The rewrite runs under the per-project lock so it neither clobbers nor is
    clobbered by a concurrent read-modify-write; the reindex runs afterwards,
    outside the lock, matching how the rest of the store keeps the derived index
    in step. ``fact`` is matched as the caller names it — not secret-stripped — so
    a leaked secret still verbatim in the record is found and scrubbed.
    """

    root = root or store_root()

    with project_lock(project_id, root=root):
        logs = _rewrite_matching_files(
            long_term_dir(project_id, root), "*.md", lambda content: _redact_log(content, fact)
        )
        transcripts = _rewrite_matching_files(
            transcripts_dir(project_id, root),
            "*.jsonl",
            lambda content: _redact_verbatim(content, fact),
        )

    # Rebuild the derived index so the scrubbed log chunks stop surfacing — but
    # only when one exists, mirroring the store's "keep in step, never conjure"
    # convention (ADR 0011). Transcripts are not indexed, so they need no rebuild.
    if index_db_path(root).exists():
        reindex(root)

    return ErasureResult(logs, transcripts)


def _rewrite_matching_files(directory: Path, pattern: str, redactor: Callable[[str], str]) -> int:
    """Rewrite each file the redactor changes; return how many files changed.

    A file whose content the redactor leaves untouched is never rewritten, so the
    count reflects genuine erasures and an untouched file keeps its mtime.
    """

    if not directory.exists():
        return 0

    rewritten = 0
    for path in sorted(directory.glob(pattern)):
        original = path.read_text(encoding="utf-8")
        redacted = redactor(original)
        if redacted != original:
            write_atomic(path, redacted)
            rewritten += 1
    return rewritten


def _redact_log(content: str, fact: str) -> str:
    """Redact ``fact`` from one Markdown daily log, line by line.

    Headings are structural and kept verbatim. For every other line the fact's
    verbatim span is replaced first (surgical, so unrelated content in a bundled
    bullet survives); failing that, a line whose entry body the shared matcher
    judges the same fact — a reworded restatement — has its body replaced whole.
    """

    pattern = _verbatim_pattern(fact)
    lines: list[str] = []
    for line in content.splitlines():
        if line.startswith("#"):
            lines.append(line)
            continue

        # Surgical: replace a verbatim occurrence of the fact wherever it sits.
        if pattern is not None and pattern.search(line):
            lines.append(pattern.sub(REDACTED, line))
            continue

        # Restatement: a reworded entry with no verbatim span — replace its body,
        # keeping the bullet/date prefix so the log still shows something was here.
        prefix, body = _split_entry(line)
        if body and is_same_fact(body, fact):
            lines.append(prefix + REDACTED)
            continue

        lines.append(line)

    trailing = "\n" if content.endswith("\n") else ""
    return "\n".join(lines) + trailing


def _redact_verbatim(content: str, fact: str) -> str:
    """Replace every verbatim occurrence of ``fact`` in ``content`` with the marker.

    Used for the JSONL transcript archive, where the marker's plain characters
    keep each record parseable and whole-line replacement is deliberately avoided.
    """

    pattern = _verbatim_pattern(fact)
    return pattern.sub(REDACTED, content) if pattern is not None else content


def _split_entry(line: str) -> tuple[str, str]:
    """Split a log line into its bullet/date prefix and its entry body."""

    match = _ENTRY_PREFIX_RE.match(line)
    if match is None:
        return "", line
    return match.group(1), match.group(2)


def _verbatim_pattern(fact: str) -> re.Pattern[str] | None:
    """A case-insensitive, whitespace-tolerant pattern matching ``fact`` verbatim.

    The fact's word run is matched with ``\\s+`` between tokens so a copy whose
    whitespace was collapsed on capture still matches. Returns ``None`` for a fact
    with no word tokens, which must never match (and never redact the whole file).
    """

    tokens = fact.split()
    if not tokens:
        return None
    return re.compile(r"\s+".join(re.escape(token) for token in tokens), re.IGNORECASE)
