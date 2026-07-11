# Concurrency: per-project locking, append-only writes, and the index as derived state

Multiple simultaneous sessions are the normal case — several terminals, several projects, plus detached capture processes — so every shared artefact gets an explicit discipline. Read-modify-write of any store Markdown artefact (`short-term.md`, a daily log's sections, the permanent bundle and its `index.md`, `registry.json`) takes a per-project advisory file lock first; daily-log capture entries are pure appends written with `O_APPEND` semantics; `index.db` opens in WAL mode with a busy timeout, and capture inserts are atomic insert-or-ignore keyed on the idempotency key, so a double fire cannot duplicate. The index is derived state: it is rebuildable from the Markdown files and never the source of truth, a `reindex` command ships with the first indexing stage, and corruption is recovered by rebuild, never repaired in place. Where last-writer-wins remains possible despite the lock (two sessions editing the same short-term entry), the lock plus a re-read-before-write inside it reduces the window, and the residual is documented rather than denied.

## Considered Options

- **No coordination, rely on personal-scale luck** (the implicit first cut) — rejected: two concurrent sessions in one project silently lose curated writes, the exact failure a memory system exists to prevent.
- **A daemon serialising all writes** — rejected: a new runtime, against the no-new-infrastructure principle.
- **Per-project file locks, append-only logs, WAL, and a rebuildable derived index** (chosen).

## Consequences

- Fire-and-forget processes must log failures to the store's log file (see the failure-visibility requirement in the vision) — detached must not mean unobservable.
- `mimer reindex` converts index corruption and embedding-model switches from disasters into routine operations.
