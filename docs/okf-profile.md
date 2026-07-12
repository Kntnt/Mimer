# Mimer's OKF profile

Mimer stores permanent memory in the [Open Knowledge Format](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md) (OKF). This document pins what that means: the spec version Mimer targets, the OKF constructs it relies on, the keys Mimer adds on top, and the fallback stance if the spec moves. It exists so the bundle's meaning is recorded in this repository, not only behind an external URL.

## Pinned version and provenance

Mimer targets **OKF v0.1**, at the time of writing a *draft* published in the `GoogleCloudPlatform/knowledge-catalog` repository (Apache 2.0, explicitly "not an official Google product"). Bundles written by Mimer declare `okf_version: 0.1`. A verbatim copy of the pinned SPEC.md is vendored under `docs/okf/` so the exact text Mimer was written against survives upstream changes.

## OKF constructs Mimer relies on

- **Bundle** — a directory of Markdown files with YAML frontmatter; Mimer's bundle is `~/.mimer/permanent/`. The spec describes itself as intentionally minimal, which is the property Mimer is buying.
- **Concept files** — one Markdown file per concept, with frontmatter. A concept's OKF id is its file path within the bundle minus the `.md` suffix.
- **`index.md`** — the bundle index for progressive disclosure: a compact, human- and agent-readable table of contents naming each Concept with a one-line hook, so a reader loads the index first and individual Concepts on demand. Mimer regenerates it on every write to the bundle; it is derived, never hand-authored.
- **Links** — OKF path links between concepts. The spec tolerates broken links; Mimer does not rely on that leniency — see the rename protocol below.
- **`# Citations`** — the numbered citations section; every Mimer Concept cites its sources there.
- **`timestamp`** — last meaningful change, as the spec defines it.

## Mimer frontmatter extensions

OKF permits producer-defined keys. Mimer adds, and other OKF consumers may ignore:

- `id` — a stable ULID; the identity that survives rename, merge and split (ADR 0015).
- `pinned` — `true` marks a profile Concept, always injected with the snapshot; pinning is never expressed by directory placement (ADR 0015).
- `origin` — the project id the Concept was distilled or written from (ADR 0013).
- `scope` — `project` (recallable only within its origin) or `global` (the cross-project second brain); project-scoped is the default for distilled facts (ADR 0013).
- `status` / `supersedes` / `superseded_by` — the supersession chain for facts that change; recall down-ranks superseded Concepts (ADR 0015).

## Discipline on top of the format

- **Stable identity**: renames, merges and splits run as one atomic operation that rewrites inbound links, regenerates `index.md` and reindexes `index.db` (ADR 0015).
- **Citations that survive**: every citation quotes a short excerpt of its source, so it stays checkable if the cited log moves or a cited commit is rewritten; registry reconciliation triggers a citation-fixup pass.
- **Granularity**: one claim, decision or preference per Concept — if two sentences can be true independently, they are two Concepts.

## Fallback stance

OKF is young and may change or be abandoned. The exposure is bounded by design: Mimer's Concepts are plain Markdown with YAML frontmatter, every semantic Mimer needs lives in its own documented keys, and the vendored spec records what v0.1 said. If OKF dies, the bundle remains fully functional Mimer storage and ordinary readable Markdown; if OKF moves, migration is a frontmatter rewrite, and the pinned version makes the diff computable. The honest interop claim is therefore: readable, portable plain text following a published, vendor-neutral spec — not membership in an ecosystem of OKF-aware memory tools, which does not yet exist.
