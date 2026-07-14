# Project identity: derived, confirmed, one memory per repository

Supersedes ADR 0008. That decision resolved identity through marker → normalised remote → path, with a `.mimer` marker file whose distinctive purpose was splitting several memories out of one repository (the monorepo case) and maximising clone portability. Against the five requirements the marker machinery earns nothing a solo practitioner needs: one repository is one client is one memory, and the registry already reconciles moves and clones without a committed marker. Identity therefore resolves through a two-step chain — the normalised git remote if the project has one, else the absolute path — reconciled through the registry. The one part that carries requirement 1 stays and is non-negotiable: identity is never bound silently. A remote or path that maps to existing memory from a previously unseen directory requires one-time confirmation, because binding the wrong directory to a client's memory is a confidentiality failure, not a mere annoyance. Remote normalisation is unchanged — scheme, credentials, user prefix and a trailing `.git` stripped, the host lowercased, multiple remotes resolving to `origin` then the first alphabetically — and git worktrees of one repository share the remote and therefore the id.

## Considered Options

- **Marker → remote → path, with a monorepo-splitting marker file** (ADR 0008) — rejected now: the marker carries no requirement for one-client-per-repo work, and adds a repository-content signal that itself needs a confirmation guard against a hostile cloned marker.
- **Remote-or-path, reconciled, confirmed before binding** (chosen) — the smallest chain that keeps memory keyed reliably and never binds a directory to another project's memory silently.

## Consequences

- A single repository holds a single memory; a genuine monorepo holding several clients' code would share one id — an accepted limitation for this audience, revisited only on a real need.
- The confirmation-before-binding flow and the registry reconciliation are retained; the marker read and the monorepo-scoping path are removed.
