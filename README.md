# Mimer

[![License](https://img.shields.io/github/license/Kntnt/Mimer)](LICENSE)
[![Latest release](https://img.shields.io/github/v/release/Kntnt/Mimer)](https://github.com/Kntnt/Mimer/releases/latest)

A Claude Code plugin that gives agents a persistent, self-curating knowledge base built on the Open Knowledge Format, with layered memory, semantic search, cited recall and real forgetting.

## Description

If you have started working with an AI coding agent such as Claude Code, you have probably noticed that its memory is shallow. Recent versions remember more than they used to — but what they remember is thin notes, not knowledge. Mimer is a plugin that gives the agent a lasting, searchable, self-curating body of knowledge about you and your work. This section explains the idea from the ground up: what the problem is, how Mimer works, why it is built the way it is, and how it compares with the better-known tools in the same space.

### The problem: agents remember notes, not knowledge

An AI agent's memory of the conversation lasts only as long as its *context window* — the limited amount of text it can hold in mind at once. Claude Code has narrowed the gap natively: its built-in auto memory writes per-project notes as it works and loads an index of them at the start of each session. That is genuinely useful, and Mimer does not pretend otherwise. But notes are not a memory system. The built-in memory cannot search by meaning — ask about "the payment system" and a note about the day you settled on Stripe stays unfound; it cites nothing, so you cannot check where a claim came from; it is confined to one project, so what you learn in one place never follows you to the next; it keeps no full record, so the exact conversation behind a decision is gone after a retention window; and it has no way to genuinely forget something on request. The longer you work with an agent, the more those gaps cost.

### What people mean by a "second brain"

The idea of a *second brain* is not new, and Mimer did not invent it. For years people have used *personal knowledge management* (PKM) tools — Obsidian, Notion, Roam and newer AI-assisted ones such as Mem and Tana — to capture what they learn into notes they can search and link, so their own memory does not have to hold everything. The name covers a family of related ideas: a *knowledge base* (an organised store of what you know), a *wiki* (linked pages of it), and methods such as *Zettelkasten* (many small, linked notes that build up into understanding).

These tools work well — for people. The catch, when your main collaborator is an AI agent, is that the knowledge lives in an app the agent cannot open. You are the courier between the two. Mimer starts from a different question: what if the second brain belonged to the agent, and it kept the brain itself?

### How Mimer works

Any memory system, human or otherwise, does three jobs: it *stores* what matters, *brings back* the right things when a session starts, and *finds* older things when you ask. Mimer does all three deliberately, across three layers that mirror how your own memory is often described.

- **Short-term memory** is what is relevant right now — the threads you are working on, the decisions still open. Small on purpose, refreshed automatically at the end of each session, and placed in front of the agent at the start of the next one, so it begins already oriented. Every session opens with a one-line note of what was loaded, so memory is never invisible.
- **Long-term memory** is the diary: a plain, dated record of what happened, session by session, with the raw transcripts archived behind it so the origin of any remembered fact can be checked.
- **Permanent memory** is what has actually been learned — durable, tidied-up knowledge, one idea per note, linked together. This is the real second brain. Knowledge that is about *you* — your preferences, your techniques, your tools — follows you from project to project; knowledge that belongs to one project or one client stays inside it.

The piece that ties them together is *distillation*: quietly, in the background, the agent lifts what is worth keeping out of the raw record and turns it into permanent knowledge — much as a night's sleep turns a day's experience into something you have genuinely learned. It checks what it already knows first, so a changed decision replaces the old one instead of contradicting it. You file nothing yourself. And when you ask about something from the past, the agent searches by *meaning* rather than exact words, then answers with a citation to where the fact came from — quoting the source, so you can check it — or admits it does not know rather than inventing an answer. When you tell it to forget something, it genuinely forgets: the fact is removed from its knowledge, blocked from being re-learned, and on request scrubbed from the raw record too.

### Why Mimer is built the way it is

A few deliberate choices set Mimer apart, and each has a reason you can weigh.

- **Knowledge is stored in an open, plain-text format** — following the [Open Knowledge Format](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md) (OKF), a published, vendor-neutral spec — rather than locked inside one app's database. Your knowledge stays readable, portable and yours: ordinary Markdown files you can open in any editor, structured to a documented spec rather than to Mimer's private whims. (Honestly said: OKF is young, and no other memory tool reads it yet — the guarantee is the plain text and the documented structure, not an ecosystem.)
- **It stores and searches everything on your own machine.** No server, no extra subscription, no separate account, no API key. Files and search index live in your home directory; summarisation runs through the Claude access you already have, and nothing else ever sees your data. Because the store concentrates everything in one place, Mimer creates it with owner-only permissions and the documentation tells you to keep it out of generic cloud sync.
- **The agent does the work, but you stay in control.** Capturing, tidying and filing happen on their own — and everything is inspectable and reversible. Ask "what do you know about me?" and get the answer; see what was learned recently; pause capture for a session; keep a project's knowledge from ever leaving it; and forget — really forget — on request. Secrets such as keys and credentials are stripped before anything is stored.
- **Memory is treated as data, never as instructions.** Whatever ends up in memory — including text that arrived from a cloned repo or a web page — is quoted and cited when it comes back, never obeyed. Changes to the always-loaded profile require your confirmation.
- **The three layers keep the right things in reach.** What the agent sees at the start of a session stays small and current, while nothing valuable is thrown away — it simply moves to the layer where it belongs.

### How Mimer differs — and the trade-offs

The market holds four kinds of tool, and only one of them is really Mimer's peer. Naming the other three clears the ground.

| Kind of tool | What it is for | Examples | How the agent-memory kind differs |
|---|---|---|---|
| **Libraries / platforms** | Building blocks you wire into an AI app you build yourself. | mem0 (SDK), cognee, Letta | You do not build with Mimer; it is a finished plugin for the agent you already use. (mem0 also ships a ready-made Claude Code plugin — that offering competes in the fourth category, backed by a hosted or self-hosted service.) |
| **Standalone knowledge apps** | A user-facing second-brain application with its own interface. | khoj | Mimer has no app or interface of its own; it lives inside the agent. |
| **Traditional PKM** | Note apps and wikis for people to fill and organise by hand. | Obsidian, Notion, Evernote | Human-driven and out of the agent's reach; Mimer is agent-driven and agent-facing. |
| **Agent memory** *(Mimer's kind)* | Giving the agent you already use a memory of what you did before. | Claude Code's built-in auto memory, claude-mem, basic-memory, Mimer | — |

Mimer complements the first three rather than replacing them: you can still build with a library, run khoj, or keep Obsidian for your own notes. The comparison that matters is inside the fourth kind.

**Inside the agent-memory category.** Below, Mimer against Claude Code's built-in auto memory and five of the most visible, actively maintained open-source projects that give a coding agent a memory: [claude-mem](https://github.com/thedotmack/claude-mem), [claude-obsidian](https://github.com/AgriciDaniel/claude-obsidian), [TencentDB Agent Memory](https://github.com/TencentCloud/TencentDB-Agent-Memory) (which targets the OpenClaw/Hermes agent rather than Claude Code), [basic-memory](https://github.com/basicmachines-co/basic-memory) and [swarmvault](https://github.com/swarmclawai/swarmvault). Mimer's column reflects the design in this repository — it is not built yet.

| Feature | Mimer | Built-in auto memory | claude-mem | claude-obsidian | TencentDB | basic-memory | swarmvault |
|---|---|---|---|---|---|---|---|
| Runs locally, on your machine | ✓ | ✓ | ✓ | ✓ | ✓ | ✓* | ✓ |
| Knowledge in open plain-text files | ✓ | ✓ | ✗ | ✓ | ✗ | ✓ | ✓ |
| Follows a published, vendor-neutral spec (OKF) | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Semantic (vector) search | ✓ | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Cited recall / provenance | ✓ | ✗ | ✓ | ✓ | ✓ | ~ | ✓ |
| Automatic session capture | ✓ | ~ | ✓ | ✓ | ✓ | ~ | ~ |
| Auto-distillation into curated knowledge | ✓ | ~ | ✓ | ✓ | ✓ | ✗ | ✓ |
| Distinct memory layers | ✓ | ~ | ~ | ✓ | ✓ | ✗ | ✓ |
| Knowledge global, memory scoped per project | ✓ | ✗ | ~ | ~ | ✗ | ✗ | ~ |
| Git history as a capture source | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| No background service required | ✓ | ✓ | ✗ | ✓ | ✓ | ~ | ✓ |
| Installable today | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

*✓ yes · ~ partial · ✗ not offered. Notes on the ~ cells: built-in auto memory saves notes when Claude judges them useful rather than capturing sessions, and reorganises its own notes rather than distilling a knowledge base; claude-mem stores observations in SQLite behind a local worker service rather than plain files, and layers retrieval (index → timeline → details) rather than memory; basic-memory's capture is an opt-in output style, its recall links to source notes without per-fact citations, and it runs as an MCP server; swarmvault ingests sessions via manual CLI commands; claude-obsidian's and swarmvault's project scoping is vault-level rather than a global/project split. basic-memory can optionally sync to its own cloud; the rest are local-only.*

**What Mimer offers.** No single row is a moat — any of these projects could add git capture in a week, and the platform's built-in memory grows with every release. Mimer's bet is the combination, plus discipline the category skips: knowledge as plain text following a published spec instead of a private database; a scope model that keeps client work confidential while your own knowledge follows you across projects; every recalled fact cited back to a checkable source, with the full transcript archived behind it; forgetting that actually spans the notes, the index and the raw record; secrets stripped before storage; and all of it with no background service, no daemon and no API key — hooks, one skill and a few scripts.

**Where the others are ahead.** They ship today; Mimer does not (see the roadmap in `docs/vision.md`). claude-mem is the category incumbent with enormous adoption, a web viewer for browsing memory in real time, and support for several agents beyond Claude Code. The built-in auto memory costs nothing to install and is on by default. basic-memory and swarmvault reach far more tools — MCP clients, Obsidian, Cursor, VS Code. swarmvault and claude-obsidian build typed knowledge graphs, and TencentDB auto-generates a user persona, richer structures than Mimer's linked concepts. swarmvault stages changes in a review queue before they land; Mimer curates automatically instead, trusting scope rules, confirmations and citations over a gate — faster, but less controlled. By riding on Obsidian, claude-obsidian and basic-memory give you a real editor and graph view for free, which Mimer has no answer to. And running locally, Mimer's search is "good enough" rather than the best a hosted model could give. Plainly: Mimer is in early development — use it at your own risk.

### How you use it

In everyday use, Mimer is meant to disappear. You install it once as a plugin, then work with your agent as you normally would. It reads you in at the start of each session — announcing in one line what it loaded — records as you go, and builds up knowledge in the background. Now and then you might say "remember this" to pin something down (the agent confirms what it stored), ask "what did we decide about X?" and get a cited answer, or ask "what do you know about me?" and see the profile it keeps. Say "forget that" and it is gone; say "pause capture" before a sensitive session and nothing is recorded. That is the whole of it — the point is that you stop being the courier.

### Key features

- three memory layers – short-term (the current session's working set, auto-refreshed at session end), long-term (the dated record, with raw transcripts archived as provenance) and permanent (durable, curated knowledge) – uniting Hermes Agent's memory model with the Second Brain / PKM tradition
- the permanent layer stored following the Open Knowledge Format (OKF) – plain-text Markdown to a published, vendor-neutral spec, pinned and profiled in `docs/okf-profile.md`
- a single store on your machine: your own durable knowledge recallable across projects, while project- and client-specific knowledge stays scoped to where it came from
- automatic distillation that promotes what matters from memory into atomic, cited knowledge – checking what it already knows first, so changed facts supersede instead of contradict
- a snapshot injected at the start of every session – the current project's short-term memory, your profile, and a compact index of what memory holds – announced in one line, never invisible
- curated writes on request – say "remember this" and the agent records it after checking what is already stored, echoing back what it did
- full-session capture with secrets stripped before storage, so the history is retained and the summarised record searchable
- semantic (vector) search with cited recall, on demand – knowledge found by meaning, every fact quoting its source
- real forgetting – "forget" removes and blocks re-learning; "redact" scrubs the raw record too
- git history read as a capture source, never written to
- a per-project, opt-in bootstrap import that fills memory from existing session and git history
- no server, no daemon, no separate subscription, no API key – hooks, one skill and a few scripts

## Requirements

- Claude Code (a recent version with plugin and hook support)
- [uv](https://docs.astral.sh/uv/), which provisions the Python environment Mimer runs on
- macOS or Linux (Windows is not yet supported)

Claude Cowork is not yet supported: Cowork runs sessions in a sandboxed VM that cannot reach a host-side store, so support is deferred until a planned capability spike establishes what is possible there.

## Installation

Mimer is a Claude Code plugin. It needs [uv](https://docs.astral.sh/uv/) (which provisions its Python environment) and a Python that can load SQLite extensions — the uv-managed CPython qualifies; some system Pythons have extension loading compiled out.

1. **Add the plugin.** Point Claude Code at this repository as a plugin — for local development, `claude --plugin-dir /path/to/Mimer`, or add the checkout as a local marketplace with `/plugin marketplace add /path/to/Mimer` followed by `/plugin install mimer@mimer`; once published, install it from its public marketplace. This registers the `SessionStart`, `Stop` and `SessionEnd` hooks and the memory skill.
2. **Provision and check.** Run the first-run install once, from the plugin directory:

   ```bash
   uv run --project /path/to/Mimer mimer-install
   ```

   This creates the `~/.mimer/` store (owner-only), verifies the interpreter can load SQLite extensions — failing loudly with an actionable message if it cannot — and pre-fetches the local embedding model so no session ever stalls on a download.
3. **Start working.** Open a session in any project; Mimer injects the snapshot at the start and records as you go. If the failure log has recent entries, the snapshot carries a one-line health notice so problems are visible, never silent.

To import history that predates Mimer, run `mimer-bootstrap` in a project once (opt-in and resumable). Inspect and correct what Mimer knows with `mimer-manage` (`profile`, `recent`, `health`, `retract`).

### Coexistence with Claude Code's native auto memory

Claude Code ships its own auto memory (on by default). Mimer works alongside it, but to avoid two systems remembering the same things divergently, the recommendation — never a requirement — is to disable native auto memory in Mimer-managed projects by setting `autoMemoryEnabled: false` in that project's Claude Code settings. Mimer builds what native memory does not attempt: retrieval by meaning with citations, a curated cross-project knowledge layer, full-history capture, git provenance, real forgetting, and bootstrap from prior history.

### Uninstalling

Remove the Mimer plugin in Claude Code to unregister its hooks. Running `mimer-uninstall` leaves your `~/.mimer/` store in place — nothing is deleted — and writes a short pointer note there explaining how to resume or how to remove your memory entirely.

## Usage

Once installed, Mimer works in the background. At the start of a session it supplies the snapshot to the agent and says so in one line; as the session proceeds the agent records what is worth keeping; and when you ask the agent to recall something, Mimer returns the relevant knowledge together with a citation to its source. Detailed usage will be documented as the interface settles.

## Questions, bugs, and feature requests

Have a usage question or something to discuss? Please use [Discussions](https://github.com/Kntnt/Mimer/discussions).

Found a bug or want to request a feature? Please [open an issue](https://github.com/Kntnt/Mimer/issues). Search the existing issues first to avoid duplicates.

## Development

Mimer is written in Python. Clone the repository and read the coding standard under [`agents.d/coding-standard/`](agents.d/coding-standard/) – `general.md` plus `python.md` – before changing code. Build and test instructions will be added as the toolchain takes shape.

## How you can contribute

Contributions are welcome, small or large. Before you start, read [`CONTRIBUTING.md`](CONTRIBUTING.md) — it covers which kinds of change are likely to be merged and how inbound licensing works.

## License

Licensed under the Apache License 2.0. The full licence text is in [`LICENSE`](LICENSE).

## Changelog

Release notes for each version live in [`CHANGELOG.md`](CHANGELOG.md).

The project follows [Keep a Changelog](https://keepachangelog.com/) and [Semantic Versioning](https://semver.org/).
