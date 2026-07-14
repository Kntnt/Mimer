# Concept identity, links, supersession and pinning

OKF's only identifier is the file path and its link model tolerates broken links by design, so an automatic writer that renames, merges and splits Concepts would rot the bundle silently. Mimer therefore adds its own identity discipline on top of the format. Every Concept carries a stable `id` (a ULID) in frontmatter; links between Concepts use OKF's path links, and any rename, merge or split runs as one atomic operation that rewrites all inbound links, regenerates `index.md` and reindexes `index.db`. Distillation is read-modify-write against the existing bundle: it recalls over permanent memory first, then creates, extends or supersedes — never blind-writes. A changed fact supersedes its predecessor via `supersedes:` on the new Concept and `status: superseded` on the old; a superseded Concept is excluded from the index, so recall drops it and never returns both sides of a contradiction as equally current. Atomicity has a granularity rule: one claim, decision or preference per Concept — if two sentences can be true independently, they are two Concepts. Citations quote a short excerpt of their source so they stay checkable when the source moves, and registry reconciliation triggers a citation-fixup pass. Pinning is the frontmatter key `pinned: true` — never directory placement, so pin state cannot change a Concept's identity — and the pinned set is capped with a demotion rule, because everything pinned is injected into every session.

## Considered Options

- **Filename-as-identity with lenient links, as bare OKF provides** — rejected: months of automatic curation converge on dangling links, ghost index entries and citations pointing at deleted files, with no error ever raised.
- **Links resolved through ids instead of paths** — rejected: diverges from OKF's own link syntax and breaks other consumers; the rename protocol keeps path links honest instead.
- **Stable frontmatter ids, an atomic rename protocol, read-modify-write distillation with supersession, and frontmatter pinning** (chosen).

## Consequences

- The Stage 5 verification gate includes a link-integrity check and a "changed fact replaces, not duplicates" case.
- `supersedes:`, `status:`, `id:`, `pinned:`, origin and scope are Mimer frontmatter extensions, documented in the OKF profile (`docs/okf-profile.md`).
