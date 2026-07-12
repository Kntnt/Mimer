# Git is a capture source, not the storage mechanism

Long-term memory is stored in Mimer's own store, not in the project's git history. Git records code changes, not the session's reasoning, decisions and dead ends; it is mutable (rebase, squash, force-push), and most sessions and most memory never become commits — so it is a lossy, biased subset, unsuited as the store. Instead, capture and bootstrap read `git log` as one additional *source*, folding commit messages — and, as intended but not-yet-built design, summarised diffs (see vision.md's *Open decisions*) — into long-term memory tagged with `git:<sha>` provenance, and a memory entry that corresponds to a commit cites its SHA.

## Considered Options

- **The project's git repository as the long-term store** — rejected for the reasons above; it would also pollute the project's history and force `git init` on non-git projects.
- **Git as a capture source and citation provenance** (chosen).
- A separate, later option: versioning and syncing Mimer's *own* store with git — transport and backup, not the memory model. Note that this option is security-sensitive: the store aggregates every project's material (see ADR 0013), so any sync would require encryption and per-scope export, never a plain push.
