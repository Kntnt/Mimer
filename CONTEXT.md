# Mimer

Mimer is a memory and knowledge system for AI coding agents. This glossary fixes the terms the design uses, so the same word means the same thing across the docs, the code and future sessions.

## Language

### Memory layers

**Short-term memory**:
The active, project-scoped working set for the current session: current threads, notes worth keeping, pending decisions. Capped.
_Avoid_: working memory, context, scratch, state.

**Long-term memory**:
The project-scoped, append-only chronological record of what happened, lightly summarised and undistilled.
_Avoid_: history, journal, capture log.

**Permanent memory**:
The global, durable body of distilled, curated knowledge — the "second brain". Built from atomic, linked Concepts.
_Avoid_: knowledge base, wiki, notes, long-term memory.

**Concept**:
A single, self-contained, atomic unit of curated knowledge in permanent memory, linked to related Concepts.
_Avoid_: note, article, page, entry.

**Profile**:
Durable, global facts about the user, realised as Concepts that are pinned so they are always injected.
_Avoid_: preferences, settings, account.

**Snapshot**:
What is injected at session start: the current project's short-term memory plus the pinned profile. Frozen for the session.
_Avoid_: dump, context load.

**Transcript**:
The raw, verbatim session record, archived unedited as the provenance behind long-term memory.
_Avoid_: log, dump.

### Operations

**Injection**:
Placing the snapshot into the agent's context automatically and silently at session start.
_Avoid_: load, prompt.

**Capture**:
The automatic, unattended recording of each exchange into long-term memory.
_Avoid_: logging, autosave.

**Curated write**:
A deliberate write, on request, into short-term or permanent memory, made only after checking against what is already stored.
_Avoid_: save, note, remember.

**Distillation**:
The automatic, agent-driven promotion of what matters from short-term and long-term memory into atomic, cited Concepts in permanent memory — the bridge from recorded memory to curated knowledge.
_Avoid_: summarisation, consolidation, promotion.

**Recall**:
Retrieving stored knowledge by meaning, returned together with its source.
_Avoid_: search, lookup, query.

**Citation**:
The source, date and location attached to a recalled item so its origin can be checked.
_Avoid_: reference, footnote, attribution.

### Scope

**Project**:
An organizing category that scopes short-term and long-term memory to the work at hand; permanent memory is not scoped by it. Not a separate store.
_Avoid_: workspace, repo, vault.

**Bootstrap**:
The one-time import of pre-existing session and git history into memory when Mimer is installed.
_Avoid_: seed, backfill, migration.
