# Mimer

Mimer is a memory and knowledge system for AI coding agents. This glossary fixes the terms the design uses, so the same word means the same thing across the docs, the code and future sessions.

## Language

### Memory layers

**Short-term memory**:
The active, project-scoped working set for the current session: current threads, notes worth keeping, pending decisions. Capped; entries are date-stamped.
_Avoid_: working memory, context, scratch, state.

**Long-term memory**:
The project-scoped, append-only chronological record of what happened, lightly summarised and undistilled.
_Avoid_: history, journal, capture log.

**Permanent memory**:
The durable, cross-project body of distilled, curated knowledge — the "second brain". Built from atomic, linked Concepts, each carrying an origin and a scope.
_Avoid_: knowledge base, wiki, notes, long-term memory.

**Concept**:
A single, self-contained, atomic unit of curated knowledge in permanent memory, linked to related Concepts. One claim, decision or preference each; identified by a stable id that survives rename.
_Avoid_: note, article, page, entry.

**Profile**:
Durable, global facts about the user, realised as Concepts that are pinned so they are always injected. Capped, with a demotion rule.
_Avoid_: preferences, settings, account.

**Snapshot**:
What is injected at session start: the current project's short-term memory, the pinned profile, and the manifest. Injected once per context lifetime; announced in one line.
_Avoid_: dump, context load.

**Manifest**:
The compact index injected with the snapshot — Concept headlines and long-term coverage dates — so the agent can judge when recall is worth invoking.
_Avoid_: table of contents, summary.

**Transcript**:
The raw, verbatim session record, archived (after redaction) as the provenance behind long-term memory. Retained and citable; not indexed.
_Avoid_: log, dump.

### Operations

**Injection**:
Placing the snapshot into the agent's context automatically at session start, once per context lifetime, with a one-line announcement of what was injected.
_Avoid_: load, prompt.

**Capture**:
The automatic, unattended recording of each exchange into long-term memory as extractive bullets, plus the session digest at session end.
_Avoid_: logging, autosave.

**Session digest**:
The one batched model call per session, at session end: it summarises the session into the daily log, refreshes short-term memory's auto-maintained sections, and archives the transcript.
_Avoid_: summary pass, wrap-up.

**Curated write**:
A deliberate write, on request, into short-term or permanent memory, made only after checking against what is already stored, and echoed back in one line.
_Avoid_: save, note, remember.

**Distillation**:
The automatic, agent-driven promotion of what matters from short-term and long-term memory into atomic, cited Concepts in permanent memory — read-modify-write against the existing bundle, with dedup and supersession. The bridge from recorded memory to curated knowledge.
_Avoid_: summarisation, consolidation.

**Recall**:
Retrieving stored knowledge by meaning, returned together with its source. Project-scoped by default; widening across projects is an explicit act.
_Avoid_: search, lookup, query.

**Citation**:
The source, date and location attached to a recalled item, quoting an excerpt so its origin can be checked even if the source moves.
_Avoid_: reference, footnote, attribution.

**Forget**:
The soft, default tier of forgetting: remove from the curated layers, write a tombstone that blocks re-distillation and filters recall; the raw record is untouched and the skill says so.
_Avoid_: delete, erase.

**Redact**:
The hard, explicit tier of forgetting: additionally rewrite the long-term logs and transcripts in place and purge the index — the one sanctioned mutation of the append-only layers.
_Avoid_: purge, scrub.

**Reindex**:
Rebuilding `index.db` from the store's files. The index is derived state; corruption means reindex, never repair.
_Avoid_: migration, vacuum.

### Scope

**Project**:
An organizing category that scopes short-term and long-term memory to the work at hand. Not a separate store.
_Avoid_: workspace, repo, vault.

**Project id**:
The identifier a project's memory is keyed by, resolved marker → normalised remote → path, reconciled through the registry, and never bound to existing memory without confirmation.
_Avoid_: project key, slug.

**Origin**:
The project a Concept was distilled or written from, recorded in its frontmatter.
_Avoid_: source project, provenance (reserved for citations).

**Scope** (of a Concept):
Where a Concept may be recalled: `project` (only within its origin) or `global` (everywhere). Project-scoped is the default for distilled facts; global is earned by being client-neutral.
_Avoid_: visibility, sharing.

**Registry**:
The store-level record mapping project ids to known remotes and paths, per-project settings and import state; the mechanism that reconciles moved, renamed or cloned projects.
_Avoid_: catalog, database.

**Marker**:
The opt-in `.mimer` file at a project root carrying its project id — first in the resolution chain, but honoured against existing memory only after confirmation.
_Avoid_: anchor, tag file.

### Mechanics

**Pinned**:
The frontmatter property (`pinned: true`) that makes a Concept part of the profile and injects it with every snapshot. Never expressed by directory placement.
_Avoid_: starred, favourite.

**Cap**:
The size bound on short-term memory (and on the pinned set) that triggers promote-then-evict maintenance. The engine that feeds distillation.
_Avoid_: limit, quota.

**Judgment rules**:
The editable prose instructions inside the memory skill that decide salience, durability, confidentiality classification and trigger-phrase disambiguation.
_Avoid_: heuristics, policy.

**Tombstone**:
The durable record of a forgotten fact's identity, consulted by distillation (never re-promote) and recall (never surface).
_Avoid_: blocklist entry, deletion marker.

**Announcement queue**:
The per-project queue of newly distilled Concept titles awaiting the next snapshot's announcement line. Appends are lockless; clearing is at-least-once — only the titles a snapshot actually carried, only after it was emitted.
_Avoid_: notification list, pending titles, distilled queue.

**Bootstrap**:
The per-project, opt-in, resumable import of pre-existing session and git history into memory, finishing with a distillation pass that populates permanent memory.
_Avoid_: seed, backfill, migration.
