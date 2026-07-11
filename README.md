# Mimer

[![License](https://img.shields.io/github/license/Kntnt/Mimer)](LICENSE)
[![Latest release](https://img.shields.io/github/v/release/Kntnt/Mimer)](https://github.com/Kntnt/Mimer/releases/latest)

A Claude Code and Claude Cowork plugin that gives agents a persistent, self-curating knowledge base built on the Open Knowledge Format, with layered memory, semantic search and cited recall.

## Description

If you have started working with an AI coding agent such as Claude Code, you have probably noticed that it forgets. Close the session and everything you worked out together is gone; open a new one and you begin from a blank slate. Mimer is a plugin that gives the agent a lasting memory — and, over time, a growing body of knowledge about you and your work. This section explains the idea from the ground up: what the problem is, how Mimer works, why it is built the way it is, and how it compares with the better-known tools in the same space.

### The problem: agents forget

An AI agent's memory lasts only as long as its *context window* — the limited amount of text it can hold in mind at once. When a session ends, the reasoning, the decisions and the facts you gathered are gone, and the next session begins from nothing. You can keep notes in a separate application, but that does not close the gap: those notes sit outside the agent, so you have to find the right ones and paste them back in by hand, every time. The longer you work this way, the more you either lose or have to supply again.

### What people mean by a "second brain"

The idea of a *second brain* is not new, and Mimer did not invent it. For years people have used *personal knowledge management* (PKM) tools — Obsidian, Notion, Roam and newer AI-assisted ones such as Mem and Tana — to capture what they learn into notes they can search and link, so their own memory does not have to hold everything. The name covers a family of related ideas: a *knowledge base* (an organised store of what you know), a *wiki* (linked pages of it), and methods such as *Zettelkasten* (many small, linked notes that build up into understanding).

These tools work well — for people. The catch, when your main collaborator is an AI agent, is that the knowledge lives in an app the agent cannot open. You are the courier between the two. Mimer starts from a different question: what if the second brain belonged to the agent, and it kept the brain itself?

### How Mimer works

Any memory system, human or otherwise, does three jobs: it *stores* what matters, *brings back* the right things when a session starts, and *finds* older things when you ask. Mimer does all three deliberately, across three layers that mirror how your own memory is often described.

- **Short-term memory** is what is relevant right now — the threads you are working on, the decisions still open. Small on purpose, and placed in front of the agent automatically at the start of each session, so it begins already oriented.
- **Long-term memory** is the diary: a plain, dated record of what happened, session by session, kept in full so the exact conversation behind a decision can be found later.
- **Permanent memory** is what has actually been learned — durable, tidied-up knowledge, one idea per note, linked together. This is the real second brain, and it follows you from one project to the next.

The piece that ties them together is *distillation*: quietly, in the background, the agent lifts what is worth keeping out of the raw record and turns it into permanent knowledge — much as a night's sleep turns a day's experience into something you have genuinely learned. You file nothing yourself. And when you ask about something from the past, the agent searches by *meaning* rather than exact words — ask about "the payment system" and it still finds the day you settled on Stripe — then answers with a citation to where the fact came from, or admits it does not know rather than inventing an answer.

### Why Mimer is built the way it is

A few deliberate choices set Mimer apart, and each has a reason you can weigh.

- **Knowledge is stored in an open, plain-text format** — the [Open Knowledge Format](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md) (OKF) — rather than locked inside one app's database. Your knowledge stays readable, portable and yours: usable by the agent, by other tools and by you in any text editor.
- **It runs entirely on your own machine.** No server, no extra subscription, no separate account. Your memory is private, and the only service it needs is the Claude access you already have.
- **The agent does the work, not you.** Capturing, tidying and filing all happen on their own. This is what *AI-native* means here: the machine keeps the brain, so you are not back to maintaining notes by hand.
- **The three layers keep the right things in reach.** What the agent sees at the start of a session stays small and current, while nothing valuable is thrown away — it simply moves to the layer where it belongs.

### How Mimer differs — and the trade-offs

The market holds four kinds of tool, and only one of them is really Mimer's peer. Naming the other three clears the ground.

| Kind of tool | What it is for | Examples | How the agent-memory kind differs |
|---|---|---|---|
| **Libraries / components** | Building blocks you wire into an AI app you build yourself. | mem0, cognee, Letta | You do not build with Mimer; it is a finished plugin for the agent you already use. |
| **App back-ends** | The engine beneath a user-facing knowledge app that has its own interface. | khoj | Mimer has no app or interface of its own; it lives inside the agent. |
| **Traditional PKM** | Note apps and wikis for people to fill and organise by hand. | Obsidian, Notion, Evernote | Human-driven and out of the agent's reach; Mimer is agent-driven and agent-facing. |
| **Agent memory** *(Mimer's kind)* | Giving the agent you already use a memory of what you did before. | claude-obsidian, basic-memory, Mimer | — |

Mimer complements the first three rather than replacing them: you can still build with a library, run khoj, or keep Obsidian for your own notes. The comparison that matters is inside the fourth kind.

**Inside the agent-memory category.** Here are five of the most-starred open-source projects that give a coding agent a memory, feature by feature against Mimer: [claude-obsidian](https://github.com/AgriciDaniel/claude-obsidian), [TencentDB Agent Memory](https://github.com/TencentCloud/TencentDB-Agent-Memory) (which targets the OpenClaw/Hermes agent rather than Claude Code), [basic-memory](https://github.com/basicmachines-co/basic-memory), [claude-memory-compiler](https://github.com/coleam00/claude-memory-compiler) and [swarmvault](https://github.com/swarmclawai/swarmvault). Mimer's column reflects the design in this document — it is not built yet.

| Feature | Mimer | claude-obsidian | TencentDB | basic-memory | memory-compiler | swarmvault |
|---|---|---|---|---|---|---|
| Runs locally, your own files | ✓ | ✓ | ✓ | ✓* | ✓ | ✓ |
| Open, tool-neutral format (OKF) | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Semantic (vector) search | ✓ | ✓ | ✓ | ✓ | ✗ | ✓ |
| Cited recall / provenance | ✓ | ✓ | ✓ | ✗ | ✗ | ✓ |
| Automatic session capture | ✓ | ✓ | ✓ | ~ | ✓ | ✓ |
| Auto-distillation into curated knowledge | ✓ | ✓ | ✓ | ✗ | ✓ | ✓ |
| Distinct memory layers | ✓ | ✓ | ✓ | ✗ | ~ | ✓ |
| Knowledge global, memory scoped per project | ✓ | ~ | ✗ | ✗ | ✗ | ~ |
| Git history as a capture source | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Installable today | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ |

*✓ yes · ~ partial · ✗ not offered. basic-memory can optionally sync to its own cloud; the rest are local-only.*

**What Mimer has that the others do not.** Two rows are Mimer's alone. It is the only one that stores curated knowledge in an open, tool-neutral format rather than plain Markdown or a proprietary store, so the knowledge is not tied to Mimer at all; and it is the only one that reads git history as a capture source, citing the commit behind a decision. Its scope model is cleaner than the field's, too — durable knowledge global, raw memory scoped per project — where the others either share one vault or stay session- or project-bound. And it targets Claude Cowork as well as Claude Code.

**Where the others are ahead.** They ship today; Mimer does not yet. basic-memory and swarmvault reach far more tools — MCP clients, Obsidian, Cursor, VS Code — where Mimer is Claude Code and Cowork only. swarmvault and claude-obsidian build typed knowledge graphs, and TencentDB auto-generates a user persona, richer structures than Mimer's linked concepts. swarmvault stages changes in a review queue before they land; Mimer curates automatically instead, trusting citations over a gate — faster, but less controlled. By riding on Obsidian, claude-obsidian and basic-memory give you a real editor and graph view for free, which Mimer has no answer to. And running locally, Mimer's search is "good enough" rather than the best a hosted model could give. Plainly: Mimer is in early development — use it at your own risk.

### How you use it

In everyday use, Mimer is meant to disappear. You install it once as a plugin, then work with your agent as you normally would. It reads you in at the start of each session, records as you go, and builds up knowledge in the background. Now and then you might say "remember this" to pin something down, or ask "what did we decide about X?" and get a cited answer. That is the whole of it — the point is that you stop being the courier.

### Key features

- three memory layers – short-term (the current session's working set), long-term (the raw, searchable history) and permanent (durable, curated knowledge) – uniting Hermes Agent's memory model with the Second Brain / PKM tradition
- the permanent layer stored in the Open Knowledge Format (OKF) – an open, plain-text specification, not a proprietary note-taking app
- a single store on your machine: durable knowledge global and recallable across projects, each project's memory and history scoped to it
- automatic distillation that promotes what matters from memory into atomic, cited knowledge – the bridge that makes it a second brain, not just a log
- a snapshot injected at the start of every session – the current project's working memory plus your global profile
- agent-curated writes – the agent decides what is worth keeping and records it as it works
- full-session capture, so the complete history is retained and searchable
- semantic (vector) search with cited recall, on demand – knowledge found by meaning, every fact pointing back to its source
- git history read as a capture source, never written to
- a one-time bootstrap import that seeds memory from existing session and git history

## Requirements

- Claude Code or Claude Cowork
- A current Python 3 on the machine that runs the agent

## Installation

Mimer is in early development and is not yet published for general installation. When it is released, it will install as a plugin for Claude Code and Claude Cowork, and the steps will be documented here.

## Usage

Once installed, Mimer works in the background. At the start of a session it supplies the working-memory snapshot to the agent; as the session proceeds the agent records what is worth keeping; and when you ask the agent to recall something, Mimer returns the relevant knowledge together with a citation to its source. Detailed usage will be documented as the interface settles.

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
