# Mimer — Technical Vision and Architecture

## Purpose

This document is the authoritative technical description of what Mimer is and how it is built. It stands on its own: a session that begins with no prior context can read it, together with the domain glossary in `CONTEXT.md` and the decision records in `docs/adr/`, and carry out the next unbuilt stage without further briefing. The reader-facing overview lives in the README; this is the engineering counterpart.

Mimer is an **AI-native** memory and knowledge system for Claude Code and Claude Cowork agents, delivered as a plugin: a set of hooks, one skill and a few scripts. It stays close to established AI knowledge tools and deviates deliberately in only two ways – it stores curated knowledge in the [Open Knowledge Format](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md) (OKF) rather than an app-specific store, and it uses a three-layer memory model. Everything runs locally from plain files on your machine – no server, no separate subscription, no new runtime.

## The three jobs of a memory system

A memory system does three things, and only three. Naming them keeps the design honest, because every part of Mimer has to serve one of them.

- **Store** – when something matters, it is saved, in a known place and a known format.
- **Inject** – when a session starts, the right context loads on its own, before the user types anything.
- **Recall** – when the user asks about something from the past, it is found by meaning, not only by exact words.

Claude Code on its own does each of these poorly: it saves almost nothing unprompted, injects almost nothing at session start, and recall amounts to grepping old files by hand. Mimer exists to do all three deliberately.

## Architecture

### Lineage — two memory models, unified

Mimer unifies two traditions and glues them with a third:

- **Hermes Agent** contributes the *memory mechanism* – a small, always-injected working memory held apart from a larger durable record the agent curates rather than the user. See [Hermes Agent](https://github.com/nousresearch/hermes-agent).
- **The Second Brain / PKM tradition** (Zettelkasten, Building a Second Brain) contributes the *permanent knowledge layer* – durable, atomic, linked, cited notes that Hermes lacks.
- **AI-native tools** (retrieval by meaning, cited recall, self-organising notes) contribute the *retrieval* model.

The distinctive part is the **bridge**: an automatic, agent-driven *distillation* that promotes what matters out of recorded memory and into curated knowledge. That flow – memory becoming knowledge without a human doing the filing – is what few tools do, and what makes Mimer a second brain rather than a session log.

Mimer inherits Hermes' *layering* but not its *scope*. Hermes anchors its store to a per-user home directory – `~/.hermes` (`%LOCALAPPDATA%\hermes` on Windows), resolved independently of the working directory – so every launch, in every project, reads and writes the same store; the curated memory and the cross-session search index both live there, none of it derived from the directory you start in (confirmed in Hermes' source: `get_hermes_home()` in `hermes_constants.py`, with memory under `.../memories` and session state at `.../state.db`). Its "global" is therefore genuinely machine-wide, not project-local: Hermes has no notion of separate projects, and the only isolation is explicit and manual – a `HERMES_HOME` override or a named profile under `~/.hermes/profiles/` – never derived from the project you are in. Mimer parts from that in a specific way: it keeps a single physical store, but scopes its layers rather than treating everything as machine-wide. Short-term and long-term memory are project-scoped (Hermes has no such notion), while permanent memory is global – the cross-project second brain (see *Scope*).

### The three layers

- **Short-term memory** – the capped, project-scoped working set for the current session: active threads, notes worth keeping, pending decisions. Plain Markdown.
- **Long-term memory** – the project-scoped, append-only, lightly summarised chronological record of what happened, plus the raw transcripts behind it. Plain Markdown. Undistilled.
- **Permanent memory** – the global, durable body of curated knowledge: atomic, linked, cited Concepts in an OKF bundle. The second brain.

The **snapshot** injected at session start is the current project's short-term memory plus the **profile** – durable global facts about you, held as pinned permanent Concepts. Injection therefore draws from short-term memory plus a pinned slice of permanent memory, not from a separate profile layer.

### Scope — one physical store, scope per layer

Storage is one physical store; logical scope differs by layer. Short-term and long-term memory are **project-scoped**; permanent memory is **global**. This keeps durable knowledge recallable across every project – the point of a second brain – while raw session memory stays tied to the work it came from.

```
~/.mimer/
  permanent/                     # global OKF bundle — the second brain
    index.md                     # bundle index (progressive disclosure)
    <concept>.md ...             # atomic, linked, cited Concepts
    profile/                     # pinned Concepts, always injected
  projects/<project-id>/
    short-term.md                # capped working-memory snapshot (this project)
    long-term/<YYYY-MM-DD>.md    # daily capture logs (this project)
    transcripts/                 # raw session transcripts, unedited
  index.db                       # sqlite-vec + FTS5 — one hybrid index over long-term + permanent
  registry.json                  # project registry: id ↔ known remotes and paths
  .bootstrapped                  # sentinel: bootstrap runs once
```

The **project id** is resolved through a fallback chain – an explicit marker if present, else the normalised git remote, else the absolute path – and the registry lets a moved, renamed or freshly cloned project be reconciled rather than orphaned. By default no marker is written into the project; the repo stays clean.

### The machinery

Mimer ships as a plugin providing:

- a **SessionStart hook** that resolves the project id and injects the snapshot (short-term memory + pinned profile) silently
- a **memory skill** exposing curated writes ("remember this", "note that", "forget about") and the recall tool
- a **Stop hook** that captures each exchange into long-term memory in the background
- a **distiller** that promotes durable knowledge into permanent Concepts, automatically
- **indexing and search scripts** over the hybrid store, for cited recall
- a **git reader** that folds `git log` into long-term memory as one capture source
- a **one-time import script** that seeds memory from existing history

The Claude Code hook names (`SessionStart`, `Stop`) are the concrete mechanism; the Claude Cowork integration mirrors them. The models: **local, lightweight embeddings** (an ONNX Python library, no service) for search, because Anthropic offers no embeddings API and an external one would be a new subscription; **Claude Haiku**, via the agent's existing Claude access, for summarisation and distillation.

## Design principles

These constraints are load-bearing. They are the difference between a memory system and a junk drawer.

- **No new infrastructure.** Plain files, hooks, one skill, a few scripts. No server, no separate subscription, no new runtime.
- **AI-native, minimal deviation.** Stay close to established tools; the only deliberate deviations are OKF and the three-layer model.
- **One physical store; scope per layer.** Memory per project, permanent memory global.
- **OKF for permanent memory only.** Short-term and long-term memory are plain Markdown; OKF is for curated Concepts, not raw logs.
- **The snapshot is frozen for the session.** Writes take effect next session, so the agent's picture of what is true right now stays stable.
- **Short-term memory is capped, and the cap drives distillation.** When a write would exceed the cap, durable items are promoted to permanent memory and transient ones age out – they already live in long-term. Nothing is dropped silently: the cap is the engine that feeds the second brain.
- **Distillation is automatic and agent-driven.** Trust is earned the AI-native way – through provenance and citations on recall – not through an up-front human review gate.
- **Judgment rules are editable, not hardcoded.** The rules for what is worth keeping live as prose instructions inside the memory skill, so they can be read, questioned and tuned.
- **Capture is idempotent and detached.** Each turn is hashed so it is never written twice; capture runs fire-and-forget so it never delays session end.
- **Recall is by meaning, then ranked, and on demand.** Vector and keyword search run in parallel and merge, reranked by recency, source weight and project. Recall is an agent-invoked tool, not an always-on augmentation of every turn.
- **Recall is always cited, and admits ignorance.** Every recalled item carries source, date and heading; when nothing relevant is found, the agent says so.
- **Git is a capture source, never the store.** Commit messages and summarised diffs fold into long-term memory tagged `git:<sha>`; a memory entry that matches a commit cites its SHA.
- **Project identity is derived, with a registry.** Marker → remote → path, reconciled through the registry; the repo stays clean by default.
- **Bootstrap runs once**, guarded by a sentinel file.

## Implementation plan

The whole system is the goal – Mimer is adopted only once every stage is built and verified. The path there is a sequence of stages in dependency order. **Each stage must pass its verification gate before the next begins.**

**Where to start.** A session picking up this work finds its starting point by checking which stages' verification gates already pass: build the first one that does not. On a fresh checkout with no `~/.mimer/` store and no code, that is Stage 0. Treat each stage below as a brief, not a rigid spec – settle the details it leaves open, build it, verify it, then move on.

### Stage 0 – Foundations

**Build.** The Python project skeleton, the `~/.mimer/` store layout, project-id resolution (marker → remote → path) and the registry, and configuration.

**Verify.** The store initialises; the project id resolves and is stable across re-runs; the registry records the current project's remote and path as aliases.

### Stage 1 – Inject: the snapshot

**Build.** `short-term.md` with its fixed sections; the SessionStart hook that resolves the project and injects short-term memory plus the pinned profile, silently. The snapshot is frozen for the session.

**Verify.** A fresh session, asked "what were we working on?" without any reminder, answers from the snapshot alone.

### Stage 2 – Store: curated writes

**Build.** The memory skill, triggered by phrases such as "remember", "note that" and "forget about": it reads the whole of short-term memory first (dedup), then adds, replaces or removes an entry, and consolidates when the cap is reached. Judgment rules live as editable instructions inside the skill. (Routing to permanent memory arrives with Stage 5.)

**Verify.** "Remember that [fact]", end the session, start a new one – the fact is present, unprompted.

### Stage 3 – Store: capture everything

**Build.** The Stop hook: extract the last exchange, have Claude Haiku turn it into a few third-person bullets, append them to today's long-term log under an auto-captured section, and archive the raw transcript. Idempotent by hashing the turn; detached so it never blocks session end.

**Verify.** After a session, the exchange appears once in the day's log; running capture again adds nothing; session end is not delayed.

### Stage 4 – Recall: search by meaning, cited

**Build.** The `sqlite-vec` + FTS5 index over long-term memory; an indexing script (chunk by natural breaks, embed locally, store metadata: project id, source, date, heading); a search script (hybrid vector + keyword, reranked by recency, source and project); citations surfaced with every result; recall exposed as an agent-invoked tool, project-scoped by default with widen/narrow.

**Verify.** A question about something weeks old, in different words, is found and cited; widening across projects surfaces a cross-project hit; an unanswerable query returns an honest "nothing found".

### Stage 5 – Permanent memory and distillation (the second brain)

**Build.** The OKF bundle for permanent memory (atomic, linked, tagged, cited Concepts); the profile as pinned Concepts; automatic, agent-driven distillation (Haiku) triggered by the short-term cap and periodically; curated-write routing to permanent enabled; recall and the index extended over permanent memory.

**Verify.** After a stretch of work, durable facts and decisions appear as atomic, cited Concepts in permanent memory; they recall from within a different project; a short-term overflow promotes to permanent rather than being lost.

### Stage 6 – Git as a capture source

**Build.** Capture and a git reader fold `git log` messages (and summarised diffs) into long-term memory with `git:<sha>` provenance; a memory entry matching a commit cites its SHA.

**Verify.** A recent commit's message is recalled, cited with its `git:<sha>`.

### Stage 7 – Bootstrap: don't start from zero

**Build.** A one-time import that walks existing Claude Code session history and git history, extracts meaningful turns the way capture does, writes them into the long-term format under the project each belongs to, and indexes them. Guarded by the sentinel.

**Verify.** A query about a pre-install conversation returns a cited result; re-running the import does nothing.

## Verifying the whole system

With every stage built, confirm the three jobs hold end to end, and the second-brain behaviours on top:

- **Inject** – a fresh session knows what you were working on, from the snapshot alone.
- **Store** – a fact you asked it to remember survives into a new session, unprompted.
- **Recall** – a question about something weeks old, in different words, is found and cited.
- **Distil** – durable knowledge learned in one project surfaces, cited, while working in another.

If a check fails, that is the layer to debug, not the whole system – the layers are independent.

## Open decisions

Settled: the architecture, the three layers and their scope, OKF for permanent memory, the store layout, git as a source, the model stack, `sqlite-vec` + FTS5, recall as a tool, project identity via a registry, and the staged plan above. Left to settle while building – each "pick the simplest that works and revisit on a real limit": the specific local embedding model and its dimensions, the chunking parameters, the exact short-term cap, the cadence of periodic distillation, and the OKF `type`/`tags` scheme for our own Concepts.
