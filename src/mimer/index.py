"""The hybrid recall index (ADRs 0007, 0011): a single SQLite database combining
sqlite-vec vector search and FTS5 keyword search over long-term memory.

The index is derived state — rebuildable from the Markdown files at any time via
:func:`reindex`, never the source of truth. Chunks are one per Markdown heading
block of the daily logs; each carries its project, source, date and heading as
columns, so scoping, citations and reranking are plain SQL. Transcripts are not
indexed. Search merges vector and keyword hits (reciprocal-rank fusion), reranks
by recency, scopes by project, suppresses tombstoned facts, and admits ignorance
by returning nothing when nothing is relevant.

Chunk text is never redacted at insert, and needs no redaction of its own: every
insert reads from an artefact already redacted before it reached disk — the daily
logs and the permanent bundle, written through storeio — or from a Concept
redacted at creation. Because the index is derived state, redacting again at insert
could only make it diverge from the files its citations quote.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Protocol

import sqlite_vec

from mimer import clock, db
from mimer.bundle import concept_identity_text
from mimer.embedding import EMBEDDING_DIMENSIONS, embed
from mimer.longterm import daily_log_path
from mimer.paths import store_root
from mimer.store import ensure_store
from mimer.storewalk import daily_log_days, disk_project_ids
from mimer.text import STOPWORDS, truncate
from mimer.tombstones import is_suppressed, load_tombstones

INDEX_FILENAME = "index.db"

# Source prefix that marks a chunk as a permanent-memory Concept rather than a
# long-term log; Concepts obey a stricter confidentiality rule (ADR 0013).
_PERMANENT_SOURCE_PREFIX = "permanent/"

# Retrieval breadth and fusion/rerank tuning — the simplest values that work.
_CANDIDATES = 20
_RRF_K = 60
_MIN_SIMILARITY = 0.12
_RECENCY_WEIGHT = 0.3
_EXCERPT_CHARS = 240

# Heading of a Markdown block; each block becomes one chunk.
_HEADING_RE = re.compile(r"^(#{2,6})\s+(.*)$")

# Common words dropped from keyword queries so FTS matches on content, not glue.
# The retrieval stopword set (``mimer.text``): recall's FTS is its one consumer.
# Fact identity keeps its own stopword set in the matcher, so the two are tuned
# independently (issues #19, #53).
_STOPWORDS = STOPWORDS


class ConceptLike(Protocol):
    """The fields of a permanent-memory Concept the index needs (no import cycle)."""

    origin: str
    scope: str
    slug: str
    title: str
    body: str
    timestamp: str


@dataclass(frozen=True)
class Citation:
    """A cited recall result: where it came from and a checkable excerpt."""

    project_id: str
    source: str
    date: str
    heading: str
    excerpt: str
    text: str
    score: float


@dataclass(frozen=True)
class _Chunk:
    chunk_key: str
    project_id: str
    source: str
    date: str
    heading: str
    text: str
    scope: str = "project"


def index_db_path(root: Path | None = None) -> Path:
    """Path to the derived index database."""

    return (root or store_root()) / INDEX_FILENAME


def _connect(root: Path) -> sqlite3.Connection:
    """Open the index with sqlite-vec loaded and the schema ensured."""

    connection = db.connect(index_db_path(root))
    connection.enable_load_extension(True)
    sqlite_vec.load(connection)
    connection.enable_load_extension(False)
    _ensure_schema(connection)
    return connection


def _ensure_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS chunks ("
        "id INTEGER PRIMARY KEY, chunk_key TEXT UNIQUE, project_id TEXT NOT NULL, "
        "source TEXT NOT NULL, date TEXT NOT NULL, heading TEXT NOT NULL, text TEXT NOT NULL, "
        "scope TEXT NOT NULL DEFAULT 'project')"
    )
    connection.execute("CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(text)")
    connection.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks "
        f"USING vec0(embedding float[{EMBEDDING_DIMENSIONS}])"
    )


def _chunk_log(text: str, project_id: str, source: str, day: str) -> list[_Chunk]:
    """Split a daily log into one chunk per heading block."""

    chunks: list[_Chunk] = []
    heading: str | None = None
    body: list[str] = []

    def flush() -> None:
        if heading is None:
            return
        block = f"{heading}\n{'\n'.join(body)}".strip()
        key = sha256(f"{project_id}\x00{source}\x00{block}".encode()).hexdigest()[:16]
        chunks.append(_Chunk(key, project_id, source, day, heading, block))

    for line in text.splitlines():
        match = _HEADING_RE.match(line)
        if match:
            flush()
            heading = match.group(2).strip()
            body = []
        elif heading is not None:
            body.append(line)
    flush()
    return chunks


def _insert_chunks(root: Path, chunks: list[_Chunk]) -> int:
    """Embed and idempotently insert chunks; return the count of new chunks."""

    if not chunks:
        return 0

    embeddings = embed([chunk.text for chunk in chunks])
    connection = _connect(root)
    added = 0
    with connection:
        for chunk, embedding in zip(chunks, embeddings, strict=True):
            cursor = connection.execute(
                "INSERT OR IGNORE INTO chunks "
                "(chunk_key, project_id, source, date, heading, text, scope) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    chunk.chunk_key,
                    chunk.project_id,
                    chunk.source,
                    chunk.date,
                    chunk.heading,
                    chunk.text,
                    chunk.scope,
                ),
            )
            if cursor.rowcount == 0:
                continue
            rowid = cursor.lastrowid
            connection.execute(
                "INSERT INTO chunks_fts(rowid, text) VALUES (?, ?)", (rowid, chunk.text)
            )
            connection.execute(
                "INSERT INTO vec_chunks(rowid, embedding) VALUES (?, ?)",
                (rowid, sqlite_vec.serialize_float32(embedding)),
            )
            added += 1
    connection.close()
    return added


def index_daily_log(project_id: str, day: str, root: Path | None = None) -> int:
    """Index (idempotently) a project's daily log; return the count of new chunks."""

    root = root or store_root()
    path = daily_log_path(project_id, day, root)
    if not path.exists():
        return 0

    chunks = _chunk_log(path.read_text(encoding="utf-8"), project_id, f"long-term/{day}.md", day)
    return _insert_chunks(root, chunks)


def concept_chunk(
    *, origin: str, scope: str, slug: str, title: str, body: str, timestamp: str
) -> _Chunk:
    """Build an index chunk from a permanent-memory Concept's fields."""

    source = f"{_PERMANENT_SOURCE_PREFIX}{slug}.md"
    text = concept_identity_text(title, body)
    key = sha256(f"{origin}\x00{source}\x00{text}".encode()).hexdigest()[:16]
    return _Chunk(key, origin, source, (timestamp or "")[:10], title, text, scope)


def index_concept_if_present(concept: ConceptLike, root: Path | None = None) -> None:
    """Index a Concept into the search index only if the index already exists."""

    if not index_db_path(root).exists() or getattr(concept, "status", "active") == "superseded":
        return
    chunk = concept_chunk(
        origin=concept.origin,
        scope=concept.scope,
        slug=concept.slug,
        title=concept.title,
        body=concept.body,
        timestamp=concept.timestamp,
    )
    _insert_chunks(root or store_root(), [chunk])


def index_if_present(project_id: str, day: str, root: Path | None = None) -> None:
    """Index a day's log only if the index already exists (kept in step with writes)."""

    if index_db_path(root).exists():
        index_daily_log(project_id, day, root)


def reindex(root: Path | None = None) -> int:
    """Rebuild the whole index from the Markdown files; return the chunk count."""

    root = root or store_root()
    ensure_store(root)

    # The index is disposable: drop it (and its WAL sidecars) and rebuild.
    for path in (index_db_path(root), *(_sidecar(root, suffix) for suffix in ("-wal", "-shm"))):
        path.unlink(missing_ok=True)
    _connect(root).close()

    # Rebuild from every day of every project's long-term memory, enumerated by
    # the store walk so the indexer knows nothing of the projects tree's layout.
    total = 0
    for project_id in disk_project_ids(root):
        for day in daily_log_days(project_id, root):
            total += index_daily_log(project_id, day, root)

    # Index the permanent-memory Concepts too (late import avoids a cycle).
    from mimer.bundle import list_concepts

    concept_chunks = [
        concept_chunk(
            origin=concept.origin,
            scope=concept.scope,
            slug=concept.slug,
            title=concept.title,
            body=concept.body,
            timestamp=concept.timestamp,
        )
        for concept in list_concepts(root)
        if concept.status != "superseded"
    ]
    total += _insert_chunks(root, concept_chunks)
    return total


def _sidecar(root: Path, suffix: str) -> Path:
    path = index_db_path(root)
    return path.with_name(path.name + suffix)


def search(
    query: str,
    *,
    root: Path | None = None,
    project_id: str | None = None,
    projects: Sequence[str] | None = None,
    limit: int = 10,
) -> list[Citation]:
    """Hybrid, cited, tombstone-filtered search over long-term and permanent memory.

    ``project_id`` is the home project the search runs from: it governs which
    project-scoped Concepts are visible (only the home project's own, plus every
    global one — ADR 0013). ``projects`` widens which projects' *logs* are
    reached, and defaults to the home project alone; passing it never widens
    Concept visibility. With neither, logs from every project are searched and
    only global Concepts show. Returns an empty list when nothing is relevant.
    """

    root = root or store_root()
    if not index_db_path(root).exists():
        return []

    connection = _connect(root)
    try:
        candidates = _fuse(connection, query)
        if not candidates:
            return []
        rows = _fetch(connection, list(candidates))
    finally:
        connection.close()

    allowed = _allowed_projects(project_id, projects)
    tombstones = load_tombstones(root)
    results = [
        _cite(row, candidates[row["id"]], query_date=clock.today())
        for row in rows
        if _in_scope(row, allowed, home=project_id)
        and not is_suppressed(row["text"], project_id=row["project_id"], tombstones=tombstones)
    ]
    results.sort(key=lambda citation: citation.score, reverse=True)
    return results[:limit]


def _in_scope(row: sqlite3.Row, allowed: frozenset[str] | None, *, home: str | None) -> bool:
    """Whether a chunk is visible from the ``home`` project given the ``allowed``
    log set (ADR 0013).

    A permanent-memory Concept obeys a stricter rule than a log chunk: it is
    visible only when it is global or its origin is the home project itself —
    never merely because widening reached its origin. Log chunks participate in
    the (possibly widened) project set, so widening reaches other projects' logs
    without ever exposing their private Concepts.
    """

    scope: str = row["scope"]
    origin: str = row["project_id"]
    if row["source"].startswith(_PERMANENT_SOURCE_PREFIX):
        return scope == "global" or origin == home
    return allowed is None or origin in allowed


def _fuse(connection: sqlite3.Connection, query: str) -> dict[int, float]:
    """Reciprocal-rank-fuse vector and keyword hits into rowid → base score."""

    scores: dict[int, float] = {}

    # Vector hits, kept only above the relevance floor so an unanswerable query
    # contributes nothing.
    query_vector = sqlite_vec.serialize_float32(embed([query])[0])
    vector_rows = connection.execute(
        "SELECT rowid, distance FROM vec_chunks WHERE embedding MATCH ? ORDER BY distance LIMIT ?",
        (query_vector, _CANDIDATES),
    ).fetchall()
    for rank, (rowid, distance) in enumerate(vector_rows):
        if 1.0 - (distance * distance) / 2.0 >= _MIN_SIMILARITY:
            scores[rowid] = scores.get(rowid, 0.0) + 1.0 / (_RRF_K + rank)

    # Keyword hits over content words.
    fts_query = _fts_query(query)
    if fts_query:
        try:
            keyword_rows = connection.execute(
                "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY rank LIMIT ?",
                (fts_query, _CANDIDATES),
            ).fetchall()
        except sqlite3.OperationalError:
            keyword_rows = []
        for rank, (rowid,) in enumerate(keyword_rows):
            scores[rowid] = scores.get(rowid, 0.0) + 1.0 / (_RRF_K + rank)

    return scores


def _fetch(connection: sqlite3.Connection, rowids: list[int]) -> list[sqlite3.Row]:
    connection.row_factory = sqlite3.Row
    placeholders = ",".join("?" for _ in rowids)
    return connection.execute(
        "SELECT id, project_id, source, date, heading, text, scope "
        f"FROM chunks WHERE id IN ({placeholders})",
        rowids,
    ).fetchall()


def _cite(row: sqlite3.Row, base_score: float, *, query_date: date) -> Citation:
    """Apply the recency rerank and build a citation with an excerpt.

    Ranking is the fused match times recency alone: the former heading-based source
    weight is removed (issue #62), so a chunk's heading no longer influences its rank.
    That weight boosted the "session digest" heading, which ADR 0023 makes moot once
    distillation subsumes the digest, so the rank collapses to recency.
    """

    score = base_score * _recency_factor(row["date"], query_date)
    return Citation(
        project_id=row["project_id"],
        source=row["source"],
        date=row["date"],
        heading=row["heading"],
        excerpt=_excerpt(row["text"]),
        text=row["text"],
        score=score,
    )


def _recency_factor(entry_date: str, query_date: date) -> float:
    """Boost recent entries mildly (within roughly a year)."""

    try:
        days = (query_date - date.fromisoformat(entry_date)).days
    except ValueError:
        return 1.0
    return 1.0 + _RECENCY_WEIGHT * max(0.0, 1.0 - days / 365.0)


def _excerpt(text: str) -> str:
    """A short, checkable quote of a chunk (body preferred over the heading)."""

    body = text.split("\n", 1)[1].strip() if "\n" in text else text
    return truncate(body, _EXCERPT_CHARS)


def _fts_query(query: str) -> str | None:
    """Turn a natural query into an FTS5 OR-match over its content words."""

    tokens = [
        token for token in re.findall(r"[A-Za-z0-9_]+", query) if token.lower() not in _STOPWORDS
    ]
    return " OR ".join(f'"{token}"' for token in tokens) if tokens else None


def _allowed_projects(
    project_id: str | None, projects: Sequence[str] | None
) -> frozenset[str] | None:
    if projects is not None:
        return frozenset(projects)
    if project_id is not None:
        return frozenset({project_id})
    return None


def reindex_main() -> int:
    """``mimer-reindex`` entry point: rebuild the index from the files."""

    count = reindex(store_root())
    print(f"Mimer: reindexed {count} chunk(s) into {index_db_path(store_root())}.")
    return 0
