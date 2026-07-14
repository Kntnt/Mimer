# Mimer — Technical Vision and Architecture

## Purpose

This document is the authoritative technical description of what Mimer is, who it is for, and why it exists. It stands on its own: a session that begins with no prior context can read it, together with the domain glossary in `CONTEXT.md`, the decision records in `docs/adr/` and the OKF profile in `docs/okf-profile.md`, and carry the work forward without further briefing. The reader-facing overview lives in the README; this is the engineering counterpart.

Mimer is a memory system for Claude Code, delivered as a plugin: a set of hooks, one skill and a few scripts, running locally from plain files on your machine — no server, no subscription, no new runtime, no API key. It is built for one kind of person: the **solo practitioner who works across many projects — their own and several clients'.** That situation shapes every decision below, because it turns memory from a convenience into a liability the moment one client's facts can surface while you work for another.

Mimer is not, and will never become, a large system that does everything one might wish. It is, and will remain, a lightweight one that does 80% of the job 100% correctly at 0% effort. Five principles keep it lean:

- **YAGNI** — build only what today's real workflow needs; no features "in case", no flags for scenarios that have not happened.
- **KISS** — the simplest thing that solves the problem beats the most elegant; if it fits on one line, the level is right.
- **DRY** — every truth about a project or client lives in exactly one place, never copied into files that can drift apart.
- **DOTADIW** — Mimer is a memory, not a project manager, a time tracker or a CRM; it remembers what is true and what happened, and does only that.
- **Text streams as a universal interface** — everything Mimer stores is plain Markdown on disk: readable without Mimer, greppable, versionable in Git, usable by any editor, agent or script, with no lock-in to an engine.

Claude Code ships its own auto memory, but Mimer replaces it rather than layering over it. The recommended setup disables the built-in auto memory in each project where Mimer is used — a project-scoped `autoMemoryEnabled: false`, which reaches neither your other projects nor Claude's chat and Cowork memory, since those are three separate systems. Running both is not merely redundant: the built-in memory keeps its own copy of what it captures, so a fact you forget or redact in Mimer can be silently re-injected by the built-in one — a hole in the forgetting guarantee (requirement 4). Mimer therefore detects the built-in memory at session start and **warns** while it is on, offering a single command that sets the project-scoped switch for you; it never flips it silently. The README states the recommendation plainly and early. (ADR 0025.)

## The two flows

Mimer is both an *auto memory* and an *agent memory* — not two memories side by side, but one current. What the agent does is captured automatically (auto memory), and what proves durable is distilled onward into curated knowledge (agent memory).

- **Capture** is the auto-memory flow: as you work, each exchange is recorded, unattended, into a raw chronological record — kept strictly per project. This is the raw material, not the product.
- **Distillation** is the agent-memory flow, and the bridge: automatically, without you filing anything, the durable and useful parts are promoted out of the raw record into atomic, cited, curated Concepts — the second brain. A changed truth supersedes its predecessor instead of contradicting it.

Raw session and project history is therefore **always project-bound**. Distilled knowledge collects in one shared body where each element carries its own scope: client-neutral knowledge becomes **global** and follows you between projects, while client- and project-specific knowledge stays recallable only in its origin project. Distillation is the product core — it is what makes everything else possible at zero effort.

Around that current sit the surfaces that get knowledge back out: **recall** (an agent-invoked, cited search, project-scoped by default), the **session-start snapshot** that Mimer owns (your "where were we" recap for the current project, plus your global profile), and a **read-only command-line browser** for reading the whole store without starting an agent at all.

## Why Mimer exists

A solo practitioner with several clients has five hard requirements of an agent memory, and every existing solution we surveyed as of July 2026 fails at least one. It is the *conjunction* that justifies Mimer, not any single feature.

1. **Client confidentiality must be the default, not a setting.** A memory that lets client A's facts leak into a session for client B is not a small bug — it is an NDA breach and disqualifying for the whole tool. Mimer is built around this: scope is set per knowledge element at distillation, project is the default, global is earned by being client-neutral, and confidential material never leaves its origin project. For this audience it is the single strongest reason Mimer must exist.
2. **Memory without verifiability is a risk, not an asset.** The category's great failure mode is injecting wrong or stale claims into future sessions — and without sources, neither you nor the agent can tell what still holds. Mimer's recall always carries source, date and a quoted excerpt, with the archived transcript as the provenance behind it — and, in a git project, the commit's `git:<sha>` as an additional anchor — and it admits when it finds nothing. That turns memory from something you hope in into something you can check.
3. **Someone must do the librarian's job — and it should not be you.** Auto-memory tools capture the work but do not curate it; agent-memory tools curate, but from notes a human feeds them, not from the agent's own work. Mimer's distillation is the bridge between the two: automatic, agent-driven, with dedup and supersession so a changed truth replaces its predecessor rather than contradicting it. This is the core that lets the other four requirements hold at zero effort.
4. **What you tell memory to forget must stay forgotten.** Mistakes, stale facts, engagement close-outs, GDPR and NDA clean-up all demand ordered forgetting. Passive decay is not control, and a delete button is not enough if the fact is re-learned from the raw record at the next distillation. Mimer's tombstones block re-distillation; redact additionally purges the raw record and the index. Forgetting is real and two-tiered.
5. **Knowledge must outlive the tool — and cost nothing to keep.** The ecosystem is young and shifting; committing years of accumulated knowledge to a proprietary store, a cloud service or a daemon is a hostage situation. Mimer stores everything as plain Markdown in a version-pinned open format (OKF), with the search index as derived, rebuildable state — and needs no server, no subscription and no API key.

Two capabilities extend this foundation and are settled additions, not open questions:

- A **leakage guard** on the way to global scope: anything the judgment rules classify as sensitive is never promoted to global without your explicit consent — asked at the next session start, waiting project-bound until answered — while everything else is promoted but announced and reversible with a single command. The safe direction is always the default. (ADR 0027.)
- A **read-only CLI browser**: search, page through and read the whole store without starting an agent — the everyday reading surface, and the place you audit with your own eyes what has become global. (ADR 0028.)

Everything in Mimer is measured against these five requirements. Whatever carries none of them is over-engineering by definition, however well built, and is cut.

## Architecture

### The three layers

- **Short-term memory** — the working recap Mimer owns and injects at session start: active threads, pending decisions, notes worth keeping. Capped; entries date-stamped. Plain Markdown. This is the "where were we" Mimer provides in place of the built-in auto memory it replaces.
- **Long-term memory** — the project-scoped, append-only, raw chronological record of what happened, captured per turn. The archived transcripts behind it are the provenance — retained and citable, not indexed. Plain Markdown. This is the raw material distillation reads.
- **Permanent memory** — the durable body of curated knowledge: atomic, linked, cited Concepts in an OKF bundle (ADR 0002; see `docs/okf-profile.md`). The second brain. Every Concept records its origin project and a scope: client-neutral knowledge is global and follows you across projects; project-specific facts stay recallable only within their origin (ADR 0013).

The **snapshot** injected at session start is the current project's short-term memory plus the **profile** — durable global facts about you, held as pinned permanent Concepts (`pinned: true` in frontmatter, never directory placement) — plus a compact **manifest** of what memory holds (Concept headlines from the bundle index and long-term coverage dates), so the agent has grounds to judge when recall is worth invoking. Injection therefore draws from short-term memory plus a pinned slice of permanent memory, not from a separate profile layer.

### Scope — one physical store, scope per layer

Storage is one physical store; logical scope differs by layer. Short-term and long-term memory are **project-scoped**; permanent memory is the **cross-project layer**, scoped per Concept as above. This keeps durable knowledge recallable across every project — the point of a second brain — while raw session memory stays tied to the work it came from, and confidential material stays inside the project it came from.

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
  registry.json                  # project registry: id ↔ known remotes and paths, per-project settings
  tombstones.jsonl               # forgotten facts: block re-distillation, filter recall
  paused                         # marker present while a store-wide capture pause is in effect (lifts only on explicit resume)
  mimer.log                      # failure log — every detached process reports here
  locks/                         # per-project advisory locks
```

The store is created with `0700` directories and `0600` files, and it concentrates every project's material in one place — the documentation tells users to exclude `~/.mimer/` from generic sync and to treat it as secret material in backups.

### Project identity — derived, confirmed, one memory per repository

Short-term and long-term memory are keyed to a project by an id resolved through a short fallback chain: the **normalised git remote** if the project has one, else the **absolute path**. The registry (id ↔ known remotes and paths) reconciles a project that moves, is renamed or is freshly cloned, so its memory is not orphaned. Identity is never bound silently: a remote or path that maps to existing memory from a previously unseen directory requires one-time confirmation before it is honoured, because binding the wrong directory to a client's memory is a confidentiality failure, not a mere annoyance. Remote normalisation strips scheme, credentials, user prefix and a trailing `.git`, and lowercases the host, so SSH and HTTPS forms of one remote resolve identically; the first remaining ambiguity (multiple remotes) resolves to `origin`, else the first alphabetically. Git worktrees of one repository share the remote and therefore the project id. One repository is one memory: Mimer does not carry a marker-file mechanism for splitting several memories out of a single repository, because a solo practitioner keeps one client per repository and the machinery earned nothing (ADR 0022).

### The machinery

Mimer ships as a plugin providing:

- a **SessionStart hook** that resolves the project id, injects the snapshot (short-term memory + pinned profile + manifest) once per context lifetime — re-firing deliberately on compact (ADR 0016) — and announces in one line what was injected, which Concepts were distilled since the last session, which new global Concepts were promoted (with the reversal command), and any consent question a sensitive promotion is waiting on (ADR 0027); when the built-in auto memory is detected on, it warns and points to the disable command (ADR 0025)
- a **memory skill** exposing curated writes ("remember this", "note that", "forget about", "redact") that echo every write and removal in one line, a manual **"distill now"** verb that promotes the current session's durable knowledge on demand (so a long or parallel session can make its findings available to other sessions without waiting for the boundary), the recall tool, and an inspection surface: "what do you know about me?" enumerates the profile, "what did you learn recently?" lists recent Concepts with citations, and a store-health summary
- a **Stop hook** that captures each exchange into long-term memory as extractive bullets — no model call — idempotently, detached, and behind the redaction pass
- a **SessionEnd hook** that runs the session's one batched Claude Haiku pass, spawned **detached so it never delays session close**: distillation straight from the raw record — refreshing short-term memory's auto-maintained sections and promoting durable facts into Concepts — plus the transcript archive (ADRs 0009, 0023)
- a **distiller** that promotes durable knowledge into permanent Concepts — read-modify-write over the raw record with dedup and supersession (ADR 0015), **idempotent per fact** so re-running mints no duplicates and a session orphaned by a crash is picked up at the next boundary rather than lost, scope classification with the leakage guard (ADRs 0013, 0027), and rejection of instruction-shaped content (ADR 0014)
- **indexing and search scripts** over the hybrid store for cited recall, plus a `reindex` command that rebuilds the derived index from the files (ADRs 0007, 0011)
- a **read-only CLI browser** in the `mimer` command family that searches, pages and reads the whole store with the same hybrid index recall uses — no agent, no writes, full sight across scopes, so it doubles as the audit surface for the leakage guard (ADR 0028)
- a **git citation convention**: an entry that corresponds to a commit cites its `git:<sha>` with a quoted excerpt, so the citation survives history rewrites; git is not folded into memory as a bulk capture source (ADR 0021)

The Claude Code hook names (`SessionStart`, `Stop`, `SessionEnd`) are the concrete mechanism; `Stop` fires per assistant turn (never on user interrupts — a documented capture limitation), `SessionEnd` at session close. The models: **local, lightweight embeddings** (a static Python model, no service) for search, because Anthropic offers no embeddings API and an external one would be a new subscription; **Claude Haiku** for distillation, invoked as one guarded, batched, detached headless CLI pass per session — never per turn, never via a stored API key (ADRs 0006, 0009). Platform: macOS and Linux; Windows is explicitly deferred.

## Design principles

These constraints are load-bearing. They are the difference between a memory system and a junk drawer.

- **No new infrastructure.** Plain files, hooks, one skill, a few scripts. No server, no separate subscription, no new runtime, no API key.
- **Replace native memory, do not race it.** Mimer owns memory end to end; the recommended setup disables Claude Code's built-in auto memory per project, so two systems never remember the same thing divergently and a forgotten fact cannot survive in the other (ADR 0025).
- **One physical store; scope per layer.** Memory per project; permanent memory cross-project, scoped per Concept — global is earned by being client-neutral, not granted by default (ADR 0013).
- **OKF for permanent memory only**, pinned to a version and profiled in `docs/okf-profile.md`. Short-term and long-term memory are plain Markdown.
- **The snapshot is injected once per context lifetime.** The files stay live behind the skill, which is the only mid-session interface; re-injection on compact is deliberate; entries carry their dates (ADR 0016).
- **Short-term memory is capped, so the recap stays a recap.** Durable items are promoted to Concepts before anything leaves; nothing is dropped silently (ADR 0017).
- **Distillation is automatic and agent-driven** — and read-modify-write over the raw record: it recalls over the existing bundle first, then creates, extends or supersedes; a changed fact replaces its predecessor rather than contradicting it; idempotency is per fact, so a re-run mints no duplicates and a crash-orphaned session distils at the next boundary (ADRs 0004, 0015, 0023).
- **Distillation also runs on demand.** The automatic pass runs detached at the session boundary; a manual "distill now" verb lets you promote the current session's knowledge immediately, resolving any sensitive-scope consent in the moment because you are present (ADRs 0023, 0027).
- **Memory is data, not instructions.** Injected and recalled content is framed as quoted, cited information; instruction-shaped content never becomes a Concept; pinned and profile writes require confirmation; injection is announced, not invisible (ADR 0014).
- **Judgment rules are editable, not hardcoded.** Salience, durability, confidentiality and sensitivity classification, and trigger-phrase disambiguation live as prose inside the memory skill (ADRs 0018, 0027).
- **Capture is idempotent, detached and observable.** The idempotency key is (project id, turn identity), kept in a durable ledger; capture runs fire-and-forget so it never delays the session, and every failure lands in `mimer.log` — detached never means unobservable.
- **Redaction before storage.** Secret-pattern and credential-in-URL checks strip credentials at the write seam before anything is archived, summarised or indexed — deliberately shape-based, not a blanket high-entropy sweep, so provenance identifiers (git SHAs, ULIDs) survive (ADR 0020).
- **Recall is by meaning, then ranked, and on demand** — vector and keyword search merged, reranked by recency; agent-invoked, project-scoped by default, widened across projects only as an explicit act that scoped Concepts and excluded projects never participate in (ADRs 0001, 0005, 0013).
- **Recall is always cited, and admits ignorance.** Every recalled item carries source, date and heading, quoting an excerpt so the citation stays checkable; when nothing relevant is found, the agent says so.
- **Forgetting is real.** "Forget" removes from the curated layers, writes a tombstone that blocks re-distillation and filters recall; "redact" additionally purges the raw record — the one sanctioned mutation of the append-only layers (ADR 0012).
- **Confidential knowledge is guarded on the way to global.** A sensitive fact is never promoted to global scope without your explicit consent; the safe direction is the waiting direction, so an unanswered consent can never leak (ADR 0027).
- **Git is a citation source, never the store.** A memory entry that matches a commit cites its SHA with a quoted excerpt, so the citation survives history rewrites; git is not folded into memory as a bulk source (ADR 0021).
- **Project identity is derived, with a registry — and never bound silently** (ADR 0022).
- **The index is derived state.** `index.db` is rebuildable from the files at any time; corruption means rebuild, not repair (ADR 0011).

## Implementation plan

The whole system is the goal — Mimer is adopted only once every stage is built and verified. The path there is a sequence of stages in dependency order. **Each stage must pass its verification gate before the next begins.**

**Gates are automated.** Every gate is an executable check — pytest against the hooks' JSON-in/JSON-out contracts, the store's contents and the index's answers, with seeded and backdated fixtures where elapsed time matters. Conversational spot-checks ("ask a fresh session…") are the stated manual residue on top, run with the built-in auto memory disabled so they test Mimer, and never the gate itself.

**Where to start.** A session picking up this work finds its starting point by inspecting which stages' components exist in code and in the store, then running the automated gates of the latest plausible stage: build the first stage whose gate does not pass. Treat each stage below as a brief, not a rigid spec — settle the details it leaves open, build it, verify it, then move on.

### Stage 0 – Foundations

**Build.** The uv-managed Python project skeleton with the plugin manifest and hook registration; the `~/.mimer/` store layout with permissions and `mimer.log`; the locking discipline and the hooks' re-entrancy guard convention (ADRs 0009, 0011); project-id resolution (normalised remote → path), the registry, and the confirmation flow for binding identity (ADR 0022); a test harness that drives hooks as JSON-in/JSON-out processes.

**Verify.** Automated: the store initialises with correct permissions; id resolution passes fixtures for multiple remotes, SSH/HTTPS equivalence, worktrees, no-git and moved projects; a new binding to existing memory demands confirmation; adding a remote to a path-keyed project reconciles rather than forking a fresh id; concurrent lock contention serialises writes; a hook invoked under the re-entrancy guard exits immediately.

### Stage 1 – Inject: the snapshot

**Build.** `short-term.md` with fixed sections (curated entries and auto-refreshed sections, all date-stamped); the SessionStart hook that resolves the project and injects short-term memory with the one-line announcement, and warns when the built-in auto memory is detected on (ADR 0025). The profile and manifest join the snapshot in Stages 5a and 4; until then the snapshot is short-term memory alone.

**Verify.** Automated: with a seeded `short-term.md`, the hook emits the snapshot and the announcement; it re-injects on a compact-source invocation; entries carry dates; a fixture with the built-in memory enabled produces the warning. Manual residue: a fresh session (built-in auto memory off), asked "what were we working on?" without any reminder, answers from the seeded snapshot alone.

### Stage 2 – Store: curated writes

**Build.** The memory skill, triggered by phrases such as "remember", "note that", "forget about" and "redact": it reads the whole of short-term memory first (dedup), then adds, replaces or removes an entry, echoing every write and removal in one line; "forget" is the soft tier — removal plus tombstone (ADR 0012); trigger-phrase disambiguation lives in the editable judgment rules. The cap only warns at this stage: promotion arrives with distillation (Stage 5b) (ADR 0017).

**Verify.** Automated: add, replace, remove and tombstone are visible in the store with the echo emitted; an over-cap write warns; a tombstoned fact stays gone. Manual residue: "remember that [fact]", end the session, start a new one — the fact is present, unprompted.

### Stage 3 – Store: capture everything

**Build.** The Stop hook: extract the last exchange from the hook payload, append extractive bullets to today's long-term log — no model call — behind the redaction pass, idempotent on (project id, turn hash) with a durable ledger, detached, failures logged. The SessionEnd hook: the one batched Haiku pass via the guarded headless CLI, **spawned detached so it never delays session close** — distillation straight from the raw record (Stage 5b) plus the transcript archive; when headless access is unavailable it degrades to extractive-only and defers distillation. Exchanges ended by user interrupt are not captured — a documented limitation.

**Verify.** Automated: the same turn captured twice lands once; a Mimer-spawned nested session captures nothing (guard test); a seeded secret never reaches log or archive (redaction test); session close is not delayed by the boundary pass; a failed Haiku pass leaves the extractive record intact and a line in `mimer.log`.

### Stage 4 – Recall: search by meaning, cited

**Build.** The `sqlite-vec` + FTS5 index over long-term memory; an indexing step wired into capture plus the `reindex` rebuild command (ADR 0011); hybrid search (vector + keyword, reranked by recency) with citations quoting excerpts; recall exposed as an agent-invoked tool, project-scoped by default, widened across projects only explicitly and never over excluded projects; tombstone suppression; the long-term coverage part of the manifest added to the snapshot.

**Verify.** Automated, on backdated fixtures: a paraphrased query about "weeks-old" content hits and cites correctly; widening is off by default and an excluded project never surfaces; a tombstoned fact does not surface; an unanswerable query returns an honest "nothing found"; deleting `index.db` and running `reindex` reproduces identical results.

### Stage 5a – Permanent memory: the bundle

**Build.** The OKF bundle per `docs/okf-profile.md`: Concept files with stable ids, links, the atomic **rename** protocol and `index.md` regeneration — merge and split are not built and the pinned profile has no cap (ADRs 0015, 0024); curated-write routing to permanent memory with scope recorded (ADR 0013) and confirmation on pinned writes (ADR 0014); the profile as pinned Concepts; the snapshot gains the profile and the Concept headlines of the manifest.

**Verify.** Automated: a Concept round-trips validly against the profile doc; a rename rewrites all inbound links and the index; a pinned write without confirmation is refused; the snapshot now carries profile and manifest.

### Stage 5b – Distillation: the bridge

**Build.** Automatic, agent-driven distillation reading the raw record: promoting durable knowledge at the session boundary (detached) and on demand via the "distill now" verb; read-modify-write against the bundle with dedup and supersession, so re-running mints no duplicates and a changed fact supersedes its predecessor — idempotency is per fact, so a crash-orphaned session distils at the next boundary (ADRs 0015, 0023); scope classification and the confidentiality rules (ADR 0013); the **leakage guard** on promotion to global — a sensitive fact waits, project-bound, for consent asked at the next session start, or resolved in the moment when "distill now" is used (ADR 0027); rejection of instruction-shaped content (ADR 0014); newly distilled Concepts and new global promotions queued for the next session's announcement.

**Verify.** Automated: a changed fact supersedes its predecessor and recall returns exactly one current answer; re-running distillation over the same record mints no duplicates; a session with no boundary pass (simulated crash) distils at the next boundary; an imperative planted in captured content never becomes a Concept; a fact distilled from project A with project scope is not recallable from project B; **a sensitive fact awaiting consent never surfaces in widened recall from another project, and is not promoted to global until consent is given.**

### Stage 5c – Recall over permanent memory, and the management surface

**Build.** The index and recall extended over permanent memory with scope enforcement in search; the inspection surface in the skill: profile enumeration ("what do you know about me?"), recent distillations with citations, store health (sizes, counts, last distillation, recent failures from `mimer.log`); a correction affordance that retracts or edits a Concept on request; the per-project settings surfaced and honoured through `mimer-manage` (capture on/off, distill-to-global on/off, participation in widened recall, and the session pause), plus the `disable-native-memory` convenience command (ADR 0025).

**Verify.** Automated: a global Concept distilled under project A recalls, cited, from project B, while a project-scoped one does not; profile enumeration matches the injected profile exactly; a retracted Concept stops surfacing; `disable-native-memory` writes the project-scoped setting and nothing else.

### Stage 6 – Git as a citation source

**Build.** The `git:<sha>` citation convention: a memory entry that corresponds to a commit cites its SHA with a quoted excerpt, behind the redaction pass, so the citation survives a history rewrite. Git is not folded into memory as a bulk capture source, and summarised diffs are not built (ADR 0021).

**Verify.** Automated: an entry matching a commit is recalled, cited with its `git:<sha>`; after a simulated history rewrite the citation's excerpt still checks out.

### Stage 7 – The read-only CLI browser

**Build.** A read-only browser in the `mimer` command family: search the whole store with the same hybrid index recall uses (local embeddings, no model call, no network), page through the hit list, and read a chosen hit as paginated text with source and date shown. It performs no writes — no forget, no redact — and reads across every scope without filtering, because scope protects clients from each other in the agent's recall, not the user from their own memory; full sight is the point, since this is also the audit surface for the leakage guard (ADR 0028).

**Verify.** Automated: a query returns the same hits recall would, unfiltered by scope; the browser performs no writes against a read-only store fixture; a chosen hit renders with its source and date.

### Stage 8 – Packaging and first run

**Build.** The installable plugin: install flow, uv-managed environment provisioning, an interpreter capability check (SQLite extension loading is compiled out of some system Pythons), embedding-model pre-fetch, first-run store creation, health surfacing at SessionStart when `mimer.log` has fresh failures, the native-memory detection warning and `disable-native-memory` guidance (ADR 0025), the uninstall story (hooks removed, store left in place with a pointer).

**Verify.** Automated, on a clean machine or container: installing Mimer and running the Stage 1–4 gates passes without manual wiring; uninstalling removes every hook and leaves the store.

## Verifying the whole system

With every stage built, confirm the jobs hold end to end, as an automated suite plus the manual residue:

- **Inject** – a fresh session knows what you were working on, from the snapshot alone.
- **Store** – a fact you asked it to remember survives into a new session, unprompted.
- **Recall** – a question about something weeks old, in different words, is found and cited.
- **Distil** – durable, client-neutral knowledge learned in one project surfaces, cited, while working in another.
- **Scope** – a project-scoped fact never surfaces outside its origin project, and a sensitive fact awaiting consent is never promoted or widened.
- **Forget** – a forgotten fact stops surfacing everywhere; a redacted one is gone from the record.

If a check fails, that is the layer to debug, not the whole system — the layers are independent.

## Open decisions

Settled: the architecture, the three layers and their scope model, OKF for permanent memory (pinned and profiled), the store layout, git as a citation source, the model stack and its detached invocation, `sqlite-vec` + FTS5 with the index as derived state, recall as a tool, project identity via a registry with confirmed binding, forgetting semantics, the leakage guard and the CLI browser, the trust boundary, and the staged plan above. Settled at the Stage 4 gate: the embedding model is model2vec's `minishlab/potion-base-8M` (static, CPU-only), at **256 dimensions**, with vectors unit-normalised so an L2 distance reads as cosine similarity; **chunking is one chunk per Markdown heading block** of the daily long-term logs; the fixed short-term sections are `Active threads`, `Pending decisions` (auto-refreshed) and `Notes` (curated). Left to settle while building — each "pick the simplest that works and revisit on a real limit": the exact short-term cap and the snapshot and profile token budgets, and the OKF `type`/`tags` scheme for our own Concepts (due at Stage 5a). Deferred to a real limit: **periodic background distillation** during long sessions — the automatic pass runs at the boundary and the "distill now" verb covers the impatient case, so a timed or volume-triggered mid-session pass waits until an observed long-session need justifies the extra Haiku calls (it would never be a daemon — at most a capture-volume trigger on the already-detached path). Cut, not deferred: **bootstrap** (import of pre-existing session history), which hung on Claude Code's undocumented, shifting transcript format and carried none of the five requirements (ADR 0026); **git as a bulk capture source** and its **summarised diffs**, reduced to the citation convention (ADR 0021).
