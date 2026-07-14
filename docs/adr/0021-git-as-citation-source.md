# Git is a citation source, not a capture source

Supersedes ADR 0003. That decision made git a *capture source* — folding `git log` messages, and as intended-but-unbuilt design summarised diffs, into long-term memory. Measured against the five requirements, the bulk fold carries none: session capture already records the work done through Mimer, so the marginal content — commits made outside a session — duplicates or clutters more than it helps, while the summarised-diff extension would add a model call to the session's batched work for no requirement at all. What *does* carry requirement 2 (verifiability) is the citation: a memory entry that corresponds to a commit cites its `git:<sha>` with a quoted excerpt, so the citation stays checkable even after a history rewrite. Mimer therefore keeps the citation convention and drops git as a bulk capture source; summarised diffs are cut, not deferred.

## Considered Options

- **Git as a bulk capture source** (ADR 0003) — rejected now: it folds content session capture already holds, carries no requirement, and invites the diff-summarising model call.
- **Git as a citation source only** (chosen) — the `git:<sha>` provenance anchor on entries that match a commit, and nothing folded in bulk.

## Consequences

- Verifiability does not depend on git: the backbone is the cited excerpt and the archived transcript, both git-free, so a non-git project — its identity resolved by path (ADR 0022) — has full verifiability. The SHA is an additional anchor when it applies.
- The Stage 6 build shrinks to the citation convention; there is no git reader folding `git log`.
