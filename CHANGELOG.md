# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Technical vision and architecture (`docs/vision.md`), including a staged, independently verifiable build plan.
- Domain glossary (`CONTEXT.md`) fixing the project's vocabulary.
- Eight architecture decision records under `docs/adr/`: the store's scope, the three-layer memory model with OKF for curated knowledge, git as a capture source, automated distillation, agent-invoked recall, the model stack, the vector store, and project identity.

### Changed

- README rewritten as a ground-up guide for newcomers, with a comparison of Mimer against the popular agent-memory projects and the adjacent tool categories.
- `AGENTS.md` now directs agents to the glossary and the architecture decision records.

## [0.1.0] – 2026-07-11

### Added

- Initial release.

[Unreleased]: https://github.com/Kntnt/Mimer/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Kntnt/Mimer/releases/tag/v0.1.0
