# Local vector store: sqlite-vec with SQLite FTS5

Mimer's retrieval store is a single SQLite database using the sqlite-vec extension for vector search and SQLite FTS5 for keyword search, so the hybrid search runs in one file with no service or daemon. Metadata — project id, source file, date, heading and git provenance — are ordinary columns, making project scoping, citations and reranking plain SQL. This matches the single-portable-store and no-new-infrastructure principles; personal-scale data keeps brute-force or simple ANN adequate, and LanceDB is the next step up only if a real limit is hit.

## Considered Options

- **FAISS** — fast ANN, but no metadata or keyword search; would need a separate store bolted on.
- **Chroma / LanceDB** — capable embedded stores, but heavier dependencies than personal-scale data needs.
- **sqlite-vec with FTS5** (chosen) — one portable file, hybrid in one place, metadata as columns.
