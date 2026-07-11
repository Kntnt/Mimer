# Project identity: derived, with a registry and reconciliation

Short-term and long-term memory are keyed to a project by an id resolved through a fallback chain — an explicit marker if present, else the normalised git remote, else the absolute path — and Mimer keeps a project registry (id ↔ known remotes and paths) so a moved, renamed or freshly cloned project can be reconciled rather than orphaned. By default Mimer writes no marker into the project, keeping the repo clean; a committed marker is an opt-in for maximum portability, and a small link/merge action repairs a project whose new location is not recognised.

Resolution consults the registry with all identity signals together, not the chain in isolation, and identity is never bound silently: a marker or remote that maps to existing memory from a previously unseen directory requires a one-time confirmation before it is honoured ("this directory claims to be project X — link it?"), because a marker is repository content and therefore controlled by whoever authored a cloned repo; an unrecognised marker starts a new project by default. A conflict between signals — a known path that acquires a new remote, a known remote at a new path — triggers the reconciliation prompt rather than a silent fall-through to a fresh, empty id. The mechanics are pinned: the marker is a `.mimer` file at the project root containing the project id; remote normalisation strips scheme, credentials, user prefix and a trailing `.git`, and lowercases the host, so SSH and HTTPS forms of the same remote resolve identically; the first remaining ambiguity (multiple remotes) resolves to `origin`, else the first alphabetically. Git worktrees of one repository share the remote and therefore the project id; monorepo sub-projects that need separate memory use the opt-in marker.

## Considered Options

- **Absolute path alone** (as Claude Code partitions sessions) — zero-config but fragile: a move, rename or clone orphans the memory.
- **Git remote alone** — stable across clones, but missing for non-git or local-only repos, and it collides in monorepos.
- **A committed marker file as first choice** — robust, but writes into every project by default.
- **Derived id plus a registry, repo-clean by default** (chosen) — start clean, reconcile afterwards.
