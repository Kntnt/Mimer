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

Set beside the well-known tools, Mimer trades polish for reach and ownership.

| Approach | Who curates it | The agent uses it directly | Format and where it lives | Finds by meaning, with sources |
|---|---|---|---|---|
| **Mimer** | the agent, automatically | yes — it is the agent's own memory | open plain-text (OKF), on your machine | yes |
| **Obsidian** (human PKM) | you, by hand | no | local Markdown files | search; by meaning only with plugins |
| **Notion, Mem, Tana** (cloud / AI PKM) | you, or AI-assisted | no — a separate app to paste into | proprietary, in the cloud | yes, in the AI ones |
| **A plain notes file, or Hermes** (agent memory) | you or the agent | yes | plain text, on your machine | no |

**Where Mimer is strong.** The agent can use it without you copying anything across. It curates itself, so there is nothing to maintain. Answers are cited and honest about gaps, which matters most when the memory is not your own — a client's stated preference, a decision a colleague made. And because the store is open and local, you are not tied to anyone's app or cloud.

**Where the trade-offs bite.** Mimer is built for the agent, not for you to browse: there is no polished editor, no graph view, no mobile app — if you want to read and arrange notes by hand, a tool like Obsidian does that far better. Running locally means search is "good enough" rather than the best a large hosted model could give. There is no built-in sync or team collaboration; the store is yours to back up or sync as you like. And curation rests on the agent's judgment — softened by the full raw history always being kept and every answer being cited, but it is not a human librarian. Finally, and plainly: Mimer is in early development and not yet ready to install.

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
