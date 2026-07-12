# Mimer — Technical Vision and Architecture

## Purpose

This document is the authoritative technical description of what Mimer is and how it is built. It stands on its own: a session that begins with no prior context can read it, together with the domain glossary in `CONTEXT.md`, the decision records in `docs/adr/` and the OKF profile in `docs/okf-profile.md`, and carry out the next unbuilt stage without further briefing. The reader-facing overview lives in the README; this is the engineering counterpart.

Mimer is an **AI-native** memory and knowledge system for Claude Code agents, delivered as a plugin: a set of hooks, one skill and a few scripts. It stays close to established AI knowledge tools and deviates deliberately in only two ways – it stores curated knowledge in the [Open Knowledge Format](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md) (OKF) rather than an app-specific store, and it uses a three-layer memory model. Everything runs locally from plain files on your machine – no server, no separate subscription, no new runtime, no API key. Claude Cowork support is deferred behind a capability spike (ADR 0010): Cowork sessions run in a sandboxed VM that cannot reach the host store, so no document claims Cowork support in the present tense.

## The three jobs of a memory system

A memory system does three things, and only three. Naming them keeps the design honest, because every part of Mimer has to serve one of them.

- **Store** – when something matters, it is saved, in a known place and a known format.
- **Inject** – when a session starts, the right context loads on its own, before the user types anything.
- **Recall** – when the user asks about something from the past, it is found by meaning, not only by exact words.

Claude Code is no longer a blank slate here: its native auto memory (on by default since v2.1.59) writes per-repository notes and injects a `MEMORY.md` index at session start, which genuinely covers part of Store and Inject. What the platform does not attempt is the rest: retrieval by meaning with citations, a curated cross-project knowledge layer with scope and supersession, full-history capture with archived transcripts as provenance, git provenance, real forgetting, and bootstrap from pre-existing history. Mimer coexists with auto memory and builds exactly that residue (ADR 0019); its verification gates assert on Mimer's own artefacts, never on model behaviour native memory could satisfy alone.

## Architecture

### Lineage — two memory models, unified

Mimer unifies two traditions and glues them with a third:

- **Hermes Agent** contributes the *memory mechanism* – a small, always-injected working memory held apart from a larger durable record the agent curates rather than the user. See [Hermes Agent](https://github.com/nousresearch/hermes-agent).
- **The Second Brain / PKM tradition** (Zettelkasten, Building a Second Brain) contributes the *permanent knowledge layer* – durable, atomic, linked, cited notes that Hermes lacks.
- **AI-native tools** (retrieval by meaning, cited recall, self-organising notes) contribute the *retrieval* model.

The distinctive part is the **bridge**: an automatic, agent-driven *distillation* that promotes what matters out of recorded memory and into curated knowledge. That flow – memory becoming knowledge without a human doing the filing – is what few tools do, and what makes Mimer a second brain rather than a session log.

Mimer inherits Hermes' *layering* but not its *scope*. Hermes anchors its store to a per-user home directory – `~/.hermes` (`%LOCALAPPDATA%\hermes` on Windows), resolved independently of the working directory – so every launch, in every project, reads and writes the same store; the curated memory and the cross-session search index both live there, none of it derived from the directory you start in (confirmed in Hermes' source: `get_hermes_home()` in `hermes_constants.py`, with memory under `.../memories` and session state at `.../state.db`). Its "global" is therefore genuinely machine-wide, not project-local: Hermes has no notion of separate projects, and the only isolation is explicit and manual – a `HERMES_HOME` override or a named profile under `~/.hermes/profiles/` – never derived from the project you are in. Mimer parts from that in a specific way: it keeps a single physical store, but scopes its layers rather than treating everything as machine-wide. Short-term and long-term memory are project-scoped (Hermes has no such notion), while permanent memory is the cross-project layer – with each Concept carrying an origin and a scope, so only client-neutral knowledge travels globally (see *Scope*).

### The three layers

- **Short-term memory** – the capped, project-scoped working set for the current session: active threads, notes worth keeping, pending decisions. Entries are date-stamped. Plain Markdown.
- **Long-term memory** – the project-scoped, append-only, lightly summarised chronological record of what happened. The raw transcripts behind it are archived alongside as provenance – retained and citable, but not indexed. Plain Markdown.
- **Permanent memory** – the durable body of curated knowledge: atomic, linked, cited Concepts in an OKF bundle (see `docs/okf-profile.md`). The second brain. Every Concept records its origin project and a scope: client-neutral knowledge is global and follows you across projects; project-specific facts stay recallable only within their origin (ADR 0013).

The **snapshot** injected at session start is the current project's short-term memory plus the **profile** – durable global facts about you, held as pinned permanent Concepts (`pinned: true` in frontmatter, never directory placement) – plus a compact **manifest** of what memory holds (Concept headlines from the bundle index and long-term coverage dates), so the agent has grounds to judge when recall is worth invoking. Injection therefore draws from short-term memory plus a pinned slice of permanent memory, not from a separate profile layer.

### Scope — one physical store, scope per layer

Storage is one physical store; logical scope differs by layer. Short-term and long-term memory are **project-scoped**; permanent memory is the **cross-project layer**, scoped per Concept as above. This keeps durable knowledge recallable across every project – the point of a second brain – while raw session memory stays tied to the work it came from, and confidential material stays inside the project it came from.

```
~/.mimer/
  permanent/                     # OKF bundle — the second brain (see docs/okf-profile.md)
    index.md                     # bundle index (progressive disclosure), regenerated by Mimer
    <concept>.md ...             # atomic, linked, cited Concepts; profile = pinned via frontmatter
  projects/<project-id>/
    short-term.md                # capped short-term memory (this project)
    long-term/<YYYY-MM-DD>.md    # daily long-term logs (this project)
    transcripts/                 # raw session transcripts, archived as provenance; not indexed
  index.db                       # sqlite-vec + FTS5 — one hybrid index over long-term + permanent; derived, rebuildable
  registry.json                  # project registry: id ↔ known remotes and paths, per-project settings, import state
  tombstones.jsonl               # forgotten facts: block re-distillation, filter recall
  paused                         # marker present while a store-wide capture pause is in effect (lifts only on explicit resume)
  mimer.log                      # failure log — every detached process reports here
  locks/                         # per-project advisory locks
```

The store is created with `0700` directories and `0600` files, and it concentrates every project's material in one place – the documentation tells users to exclude `~/.mimer/` from generic sync and to treat it as secret material in backups. The **project id** is resolved through a fallback chain – an explicit marker (a `.mimer` file at the project root) if present, else the normalised git remote, else the absolute path – consulting the registry with all signals together, and identity is never bound silently: a marker or remote that maps to existing memory from a new directory requires one-time confirmation, and a conflict between signals triggers reconciliation rather than a silent fresh id (ADR 0008). By default no marker is written into the project; the repo stays clean.

### The machinery

Mimer ships as a plugin providing:

- a **SessionStart hook** that resolves the project id, injects the snapshot (short-term memory + pinned profile + manifest) once per context lifetime – re-firing deliberately on compact (ADR 0016) – and announces in one line what was injected and which Concepts were distilled since the last session
- a **memory skill** exposing curated writes ("remember this", "note that", "forget about") that echo every write and removal in one line, the recall tool, and an inspection surface: "what do you know about me?" enumerates the profile, "what did you learn recently?" lists recent Concepts with citations, and a store-health summary
- a **Stop hook** that captures each exchange into long-term memory as extractive bullets – no model call – idempotently, detached, and behind a redaction pass
- a **SessionEnd hook** that runs the session's one batched Claude Haiku call: the session digest into long-term memory, the refresh of short-term memory's auto-maintained sections, and the transcript archive (ADR 0009)
- a **distiller** that promotes durable knowledge into permanent Concepts – read-modify-write with dedup and supersession (ADR 0015), scope classification (ADR 0013), and rejection of instruction-shaped content (ADR 0014)
- **indexing and search scripts** over the hybrid store for cited recall, plus a `reindex` command that rebuilds the derived index from the files (ADR 0011)
- a **git reader** that folds `git log` into long-term memory as one capture source
- an **import script** that fills memory from existing history, per project, opt-in and resumable

The Claude Code hook names (`SessionStart`, `Stop`, `SessionEnd`) are the concrete mechanism; `Stop` fires per assistant turn (never on user interrupts – a documented capture limitation), `SessionEnd` at session close. The models: **local, lightweight embeddings** (an ONNX Python library, no service) for search, because Anthropic offers no embeddings API and an external one would be a new subscription; **Claude Haiku** for the digest and distillation, invoked as one guarded, batched headless CLI call per session – never per turn, never via a stored API key (ADR 0009). Platform: macOS and Linux; Windows is explicitly deferred.

## Design principles

These constraints are load-bearing. They are the difference between a memory system and a junk drawer.

- **No new infrastructure.** Plain files, hooks, one skill, a few scripts. No server, no separate subscription, no new runtime, no API key.
- **AI-native, minimal deviation.** Stay close to established tools; the only deliberate deviations are OKF and the three-layer model.
- **One physical store; scope per layer.** Memory per project; permanent memory cross-project, scoped per Concept — global is earned by being client-neutral, not granted by default (ADR 0013).
- **OKF for permanent memory only**, pinned to a version and profiled in `docs/okf-profile.md`. Short-term and long-term memory are plain Markdown.
- **The snapshot is injected once per context lifetime.** The files stay live behind the skill, which is the only mid-session interface; re-injection on compact is deliberate; entries carry their dates (ADR 0016).
- **Short-term memory is capped, and the cap drives distillation — promote-then-evict.** A durable item is evicted only after its promoted Concept is verified on disk; every eviction is itself a write to the daily log. Nothing is dropped silently, by construction (ADR 0017).
- **Distillation is automatic and agent-driven** — and read-modify-write: it recalls over the existing bundle first, then creates, extends or supersedes; a changed fact replaces its predecessor rather than contradicting it (ADRs 0004, 0015).
- **Memory is data, not instructions.** Injected and recalled content is framed as quoted, cited information; instruction-shaped content never becomes a Concept; pinned and profile writes require confirmation; injection is announced, not invisible (ADR 0014).
- **Judgment rules are editable, not hardcoded.** Salience, durability, confidentiality classification and trigger-phrase disambiguation live as prose inside the memory skill (ADR 0018).
- **Capture is idempotent, detached and observable.** The idempotency key is (project id, turn identity), kept in a durable ledger; capture runs fire-and-forget so it never delays the session, and every failure lands in `mimer.log` — detached never means unobservable.
- **Redaction before storage.** Secret-pattern and credential-in-URL checks strip credentials before anything is archived, summarised or indexed — deliberately shape-based, not a blanket high-entropy sweep, so provenance identifiers (git SHAs, ULIDs) survive.
- **Recall is by meaning, then ranked, and on demand** — vector and keyword search merged, reranked by recency, source weight and project; agent-invoked, project-scoped by default, widened across projects only as an explicit act that scoped Concepts and excluded projects never participate in (ADRs 0001, 0005, 0013).
- **Recall is always cited, and admits ignorance.** Every recalled item carries source, date and heading, quoting an excerpt so the citation stays checkable; when nothing relevant is found, the agent says so.
- **Forgetting is real.** "Forget" removes from the curated layers, writes a tombstone that blocks re-distillation and filters recall; "redact" additionally purges the raw record — the one sanctioned mutation of the append-only layers (ADR 0012).
- **Git is a capture source, never the store.** Commit messages fold into long-term memory tagged `git:<sha>`; a memory entry that matches a commit cites its SHA with a quoted excerpt, so the citation survives history rewrites. Summarising diffs alongside the messages is intended but not yet built (see *Open decisions*).
- **Project identity is derived, with a registry — and never bound silently** (ADR 0008).
- **The index is derived state.** `index.db` is rebuildable from the files at any time; corruption means rebuild, not repair (ADR 0011).
- **Bootstrap is per project, opt-in, resumable and idempotent.**

## Implementation plan

The whole system is the goal – Mimer is adopted only once every stage is built and verified. The path there is a sequence of stages in dependency order. **Each stage must pass its verification gate before the next begins.**

**Gates are automated.** Every gate is an executable check — pytest against the hooks' JSON-in/JSON-out contracts, the store's contents and the index's answers, with seeded and backdated fixtures where elapsed time matters. Conversational spot-checks ("ask a fresh session…") are the stated manual residue on top, run with native auto memory disabled so they test Mimer, and never the gate itself.

**Where to start.** A session picking up this work finds its starting point by inspecting which stages' components exist in code and in the store, then running the automated gates of the latest plausible stage: build the first stage whose gate does not pass. On a fresh checkout with no `~/.mimer/` store and no code, that is Stage 0. Treat each stage below as a brief, not a rigid spec – settle the details it leaves open, build it, verify it, then move on.

### Stage 0 – Foundations

**Build.** The uv-managed Python project skeleton with the plugin manifest and hook registration; the `~/.mimer/` store layout with permissions and `mimer.log`; the locking discipline and the hooks' re-entrancy guard convention (ADRs 0009, 0011); project-id resolution (marker → normalised remote → path), the registry, the confirmation flow for binding identity, and the link/merge reconciliation action (ADR 0008); a test harness that drives hooks as JSON-in/JSON-out processes.

**Verify.** Automated: the store initialises with correct permissions; id resolution passes fixtures for multiple remotes, SSH/HTTPS equivalence, worktrees, monorepo markers, no-git and moved projects; a new binding to existing memory demands confirmation; adding a remote to a path-keyed project triggers reconciliation, not a fresh id; concurrent lock contention serialises writes; a hook invoked under the re-entrancy guard exits immediately.

### Stage 1 – Inject: the snapshot

**Build.** `short-term.md` with fixed sections (their names and order are settled at build time; the classes are curated entries and auto-refreshed digest sections, all date-stamped); the SessionStart hook that resolves the project and injects short-term memory with the one-line announcement. The profile and manifest join the snapshot in Stages 5a and 4; until then the snapshot is short-term memory alone.

**Verify.** Automated: with a seeded `short-term.md`, the hook emits the snapshot and the announcement; it re-injects on a compact-source invocation; entries carry dates. Manual residue: a fresh session (native auto memory off), asked "what were we working on?" without any reminder, answers from the seeded snapshot alone.

### Stage 2 – Store: curated writes

**Build.** The memory skill, triggered by phrases such as "remember", "note that" and "forget about": it reads the whole of short-term memory first (dedup), then adds, replaces or removes an entry, echoing every write and removal in one line; "forget" is the soft tier — removal plus tombstone (ADR 0012); trigger-phrase disambiguation lives in the editable judgment rules. The cap only warns at this stage: nothing is evicted until capture exists (Stage 3), and promotion arrives with distillation (Stage 5b) (ADR 0017).

**Verify.** Automated: add, replace, remove and tombstone are visible in the store with the echo emitted; an over-cap write warns and evicts nothing; a tombstoned fact stays gone. Manual residue: "remember that [fact]", end the session, start a new one – the fact is present, unprompted.

### Stage 3 – Store: capture everything

**Build.** The Stop hook: extract the last exchange from the hook payload, append extractive bullets to today's long-term log — no model call — behind the redaction pass, idempotent on (project id, turn hash) with a durable ledger, detached, failures logged. The SessionEnd hook: the one batched Haiku call per session via the guarded headless CLI (ADR 0009) producing the session digest in the daily log, the refresh of short-term memory's auto-maintained sections, and the transcript archive; when headless access is unavailable it degrades to extractive-only and defers the digest. Eviction-as-write switches on (ADR 0017). Exchanges ended by user interrupt are not captured — a documented limitation.

**Verify.** Automated: the same turn captured twice lands once; a Mimer-spawned nested session captures nothing (guard test); a seeded secret never reaches log, digest or archive (redaction test); session end is not delayed beyond a stated bound; the digest refreshes the auto-maintained sections; a failed Haiku call leaves the extractive record intact and a line in `mimer.log`.

### Stage 4 – Recall: search by meaning, cited

**Build.** The `sqlite-vec` + FTS5 index over long-term memory — the embedding model, its dimensions and the chunking parameters are decisions due at this gate; an indexing step wired into capture and digest plus the `reindex` rebuild command (ADR 0011); hybrid search (vector + keyword, reranked by recency, source weight and project) with citations quoting excerpts; recall exposed as an agent-invoked tool, project-scoped by default, widened across projects only explicitly and never over excluded projects; tombstone suppression; the long-term coverage part of the manifest added to the snapshot.

**Verify.** Automated, on backdated fixtures: a paraphrased query about "weeks-old" content hits and cites correctly; widening is off by default and an excluded project never surfaces; a tombstoned fact does not surface; an unanswerable query returns an honest "nothing found"; deleting `index.db` and running `reindex` reproduces identical results.

### Stage 5a – Permanent memory: the bundle

**Build.** The OKF bundle per `docs/okf-profile.md`: Concept files with stable ids, links, the atomic rename protocol and `index.md` regeneration (ADR 0015); the profile as pinned Concepts with its cap and demotion rule; curated-write routing to permanent memory with scope recorded (ADR 0013) and confirmation on pinned writes (ADR 0014); the snapshot gains the profile and the Concept headlines of the manifest.

**Verify.** Automated: a Concept round-trips validly against the profile doc; a rename rewrites all inbound links and the index; the pinned cap is enforced with demotion; a pinned write without confirmation is refused; the snapshot now carries profile and manifest.

### Stage 5b – Distillation: the bridge

**Build.** Automatic, agent-driven distillation: triggered by the short-term cap — an over-cap curated write promotes durable entries before evicting them (ADR 0017) — and opportunistically at every session boundary (no daemon); read-modify-write against the bundle with dedup and supersession, so re-running over the same record mints no duplicates and a changed fact supersedes its predecessor — idempotency is per-fact, not a run marker (ADR 0015); scope classification and the confidentiality rules (ADR 0013); rejection of instruction-shaped content (ADR 0014); promote-then-evict (ADR 0017); newly distilled Concepts queued for the next session's announcement line.

**Verify.** Automated: a changed fact supersedes its predecessor and recall returns exactly one current answer; re-running distillation over the same record mints no duplicates; a failed promotion leaves the short-term entry in place and logs; an imperative planted in captured content never becomes a Concept; a fact distilled from project A with project scope is not recallable from project B.

### Stage 5c – Recall over permanent memory, and the management surface

**Build.** The index and recall extended over permanent memory with scope enforcement in search; the inspection surface in the skill: profile enumeration ("what do you know about me?"), recent distillations with citations, store health (sizes, counts, last digest and distillation, recent failures from `mimer.log`); a correction affordance that retracts or edits a Concept on request.

**Verify.** Automated: a global Concept distilled under project A recalls, cited, from project B, while a project-scoped one does not; profile enumeration matches the pinned set exactly; a retracted Concept stops surfacing.

### Stage 6 – Git as a capture source

**Build.** Capture and a git reader fold `git log` messages into long-term memory with `git:<sha>` provenance and a quoted excerpt, behind the redaction pass, triggered opportunistically on session boundaries; a memory entry matching a commit cites its SHA. First adoption folds the whole history — paging past the most recent commits, not stopping at a hundred — up to a documented safety bound whose truncation is logged rather than silent, so an enormous repo cannot stall a session boundary; later runs fold only the commits added since. Rewritten history is the stated caveat the excerpt exists for. Summarising diffs alongside the messages is deferred (see *Open decisions*).

**Verify.** Automated: a recent commit's message is recalled, cited with its `git:<sha>`; a repo with more than a hundred prior commits folds its full history on first adoption; after a simulated history rewrite the citation's excerpt still checks out; re-running the reader adds nothing.

### Stage 7 – Bootstrap: don't start from zero

**Build.** A per-project, opt-in, resumable import that walks existing Claude Code session history, extracts meaningful turns the way capture does (through the redaction pass, excluding Mimer-spawned sessions), writes them into the long-term format under the project each belongs to, indexes them, and finishes with a distillation pass that populates permanent memory, a starter profile and an initial short-term working set. (Bootstrap does not import git history; the git reader folds a repo's whole history on first adoption at a session boundary instead — Stage 6.) Import state lives per project in the registry, recorded complete only after verification. Transcript parsing is an isolated, version-tolerant adapter — the JSONL format is vendor-internal and changes between releases — and the brief states honestly that Claude Code prunes transcripts after a retention window, so the reachable history is bounded.

**Verify.** Automated: a fixture history imports once; a simulated crash mid-import resumes rather than restarts; re-running a completed import adds nothing; a query about an imported conversation returns a cited result; a project first seen after other imports still imports its own history.

### Stage 8 – Packaging and first run

**Build.** The installable plugin: install flow, uv-managed environment provisioning, an interpreter capability check (SQLite extension loading is compiled out of some system Pythons), embedding-model pre-fetch, first-run store creation, health surfacing at SessionStart when `mimer.log` has fresh failures, the uninstall story (hooks removed, store left in place with a pointer), and the coexistence guidance for native auto memory (ADR 0019).

**Verify.** Automated, on a clean machine or container: installing Mimer and running the Stage 1–4 gates passes without manual wiring; uninstalling removes every hook and leaves the store.

## Verifying the whole system

With every stage built, confirm the jobs hold end to end, as an automated suite plus the manual residue:

- **Inject** – a fresh session knows what you were working on, from the snapshot alone.
- **Store** – a fact you asked it to remember survives into a new session, unprompted.
- **Recall** – a question about something weeks old, in different words, is found and cited.
- **Distil** – durable, client-neutral knowledge learned in one project surfaces, cited, while working in another.
- **Scope** – a project-scoped fact never surfaces outside its origin project.
- **Forget** – a forgotten fact stops surfacing everywhere; a redacted one is gone from the record.

If a check fails, that is the layer to debug, not the whole system – the layers are independent.

## Open decisions

Settled: the architecture, the three layers and their scope model, OKF for permanent memory (pinned and profiled), the store layout, git as a source, the model stack and its invocation mechanism, `sqlite-vec` + FTS5 with the index as derived state, recall as a tool, project identity via a registry with confirmed binding, forgetting semantics, the trust boundary, and the staged plan above. Settled at the Stage 4 gate: the embedding model is model2vec's `minishlab/potion-base-8M` (static, CPU-only, no ONNX runtime), at **256 dimensions**, with vectors unit-normalised so an L2 distance reads as cosine similarity; **chunking is one chunk per Markdown heading block** of the daily long-term logs; the fixed short-term sections are `Active threads`, `Pending decisions` (auto-refreshed) and `Notes` (curated). Left to settle while building – each "pick the simplest that works and revisit on a real limit": the exact short-term cap and the snapshot and profile token budgets, the source weights in reranking, the exact first-adoption git backfill bound (currently a fixed commit count, logged when hit), and the OKF `type`/`tags` scheme for our own Concepts (due at Stage 5a). Settled by issue #35: per-project settings (capture, distill-to-global, participation in widened recall) live in the registry, surfaced and honoured through `mimer-manage`; there is no `config.toml` (the registry is the settings home), and a capture pause is a store-wide marker the capture and digest paths check — sticky until an explicit resume (a session ending never lifts it, so it is safe under concurrent sessions) and surfaced on every SessionStart and in `mimer-manage health` so a forgotten pause is never a silent blackout. Deferred: folding *summarised diffs* alongside commit messages (ADR 0003 keeps it as intended design; the git reader folds commit messages only today, so it would add a diff-summarising model call to the session's batched work).
