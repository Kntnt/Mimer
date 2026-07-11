# Project identity: derived, with a registry and reconciliation

Short-term and long-term memory are keyed to a project by an id resolved through a fallback chain — an explicit marker if present, else the normalised git remote, else the absolute path — and Mimer keeps a project registry (id ↔ known remotes and paths) so a moved, renamed or freshly cloned project can be reconciled rather than orphaned. By default Mimer writes no marker into the project, keeping the repo clean; a committed marker is an opt-in for maximum portability, and a small link/merge action repairs a project whose new location is not recognised.

## Considered Options

- **Absolute path alone** (as Claude Code partitions sessions) — zero-config but fragile: a move, rename or clone orphans the memory.
- **Git remote alone** — stable across clones, but missing for non-git or local-only repos, and it collides in monorepos.
- **A committed marker file as first choice** — robust, but writes into every project by default.
- **Derived id plus a registry, repo-clean by default** (chosen) — start clean, reconcile afterwards.
