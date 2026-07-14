# Concept identity: rename and supersession, without merge, split or a profile cap

Supersedes ADR 0015. Its identity discipline stands where it carries a requirement: every Concept keeps a stable `id` (a ULID), links use OKF path links, a **rename** runs as one atomic operation that rewrites inbound links and regenerates the index, and a changed fact **supersedes** its predecessor so recall never returns both sides of a contradiction — requirement 3's "a changed truth replaces its predecessor". Two parts of ADR 0015 are dropped as unbuilt over-engineering. Automatic **merge and split** of Concepts — reorganising the bundle by fusing or dividing notes with full link repair — were never built and no observed need calls for them; the granularity rule (one claim, decision or preference per Concept) is enforced at creation instead. The **pinned-set cap and demotion rule** is dropped: a solo practitioner's profile does not grow large enough to need automatic eviction, and a cap is added only on a real limit.

## Considered Options

- **Stable ids, rename, supersession, merge, split, and a capped pinned set** (ADR 0015) — rejected now: merge and split were never built and carry no requirement; the profile cap solves a problem this audience does not have.
- **Stable ids, rename and supersession only; no merge or split; no profile cap** (chosen).

## Consequences

- The Stage 5a gate keeps the rename link-integrity check and the "changed fact replaces, not duplicates" case; it drops the merge, split and pinned-cap cases.
- `supersedes:`, `status:`, `id:`, `pinned:`, `origin` and `scope` remain the Mimer frontmatter extensions (`docs/okf-profile.md`); the profile-cap behaviour is removed.
