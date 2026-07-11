# Mimer

[![License](https://img.shields.io/github/license/Kntnt/Mimer)](LICENSE)
[![Latest release](https://img.shields.io/github/v/release/Kntnt/Mimer)](https://github.com/Kntnt/Mimer/releases/latest)

A Claude Code and Claude Cowork plugin that gives agents a persistent, self-curating knowledge base built on the Open Knowledge Format, with layered memory, semantic search and cited recall.

## Description

Large language model agents start each session with no memory of the last one. Mimer gives them one. It is a knowledge base – a *second brain* – that a Claude Code or Claude Cowork agent reads from at the start of a session and writes back to as it works, so what the agent learns in one session is available in the next.

The knowledge itself lives in the Open Knowledge Format (OKF), an open, plain-text [specification](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md), rather than inside a single note-taking application such as Obsidian. The store stays readable, portable and owned by you – usable by the agent, by other tools and by hand.

### Key features

- storage in the Open Knowledge Format (OKF) – an open, plain-text specification, not a proprietary note-taking app
- a layered memory model adapted from Hermes Agent, keeping recent working memory and long-term knowledge distinct
- a Layer-1 working-memory snapshot – `memory.md` and `user.md` – injected at the start of every session
- agent-curated writes – the agent decides what is worth keeping and records it as it works
- full-session capture, so the complete session is retained alongside the curated summary
- semantic (vector) search that recalls knowledge by meaning rather than exact keywords
- source citations on recall, so every recalled fact points back to where it came from
- a one-time bootstrap import that seeds the knowledge base from existing session history

### The problem

An agent's memory lasts only as long as its context window. When a session ends, the reasoning, the decisions and the facts gathered along the way are gone, and the next session starts from nothing. Notes kept in a separate application do not close the gap, because they sit outside the agent and have to be found and pasted back in by hand. The longer you work with an agent, the more of that accumulated understanding you lose or have to supply again.

### How this plugin helps

Mimer keeps the agent's knowledge in a store it can reach directly. At the start of each session it injects a Layer-1 working-memory snapshot – a short, current picture of the user and the work in hand, held in `memory.md` and `user.md` – so the agent begins already oriented. During the session the agent curates that store itself, writing back what is worth keeping, while the full session is captured for later reference.

The layered memory model is adapted from [Hermes Agent](https://github.com/nousresearch/hermes-agent). On top of it Mimer adds semantic search, so knowledge is recalled by meaning rather than exact wording, and citations, so each recalled fact carries a pointer back to its source. Existing session history can be imported once, in a bootstrap step, to give the knowledge base a starting body of material.

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
