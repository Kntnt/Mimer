# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Technical vision and architecture (`docs/vision.md`), including a staged, independently verifiable build plan.
- Domain glossary (`CONTEXT.md`) fixing the project's vocabulary.
- Eight architecture decision records under `docs/adr/`: the store's scope, the three-layer memory model with OKF for curated knowledge, git as a capture source, automated distillation, agent-invoked recall, the model stack, the vector store, and project identity.
- Eleven further architecture decision records (0009–0019), from a multi-lens critical design review: Claude access from hooks, Claude Code first with Cowork deferred, concurrency and the derived index, forgetting across layers, scoped permanent memory, the memory-is-data trust boundary, Concept identity and supersession, the snapshot lifecycle, cap mechanics with no silent loss, editable judgment rules, and coexistence with Claude Code's native auto memory.
- Mimer's OKF profile (`docs/okf-profile.md`): the pinned spec version, the constructs relied on, Mimer's frontmatter extensions, and the fallback stance.

### Changed

- README rewritten as a ground-up guide for newcomers, with a comparison of Mimer against the popular agent-memory projects and the adjacent tool categories.
- `AGENTS.md` now directs agents to the glossary and the architecture decision records.
- Design hardened throughout `docs/vision.md` after the review: LLM-free per-exchange capture with one batched Haiku digest per session, a SessionEnd hook, secret redaction before storage, real forget/redact semantics, Concepts scoped by origin project, a memory manifest and a management surface, automated verification gates, per-project opt-in bootstrap, and the plan restructured into Stages 0–8 (permanent memory split into 5a–5c, packaging added as Stage 8).
- README comparison rebuilt against verified facts: claude-mem and Claude Code's built-in auto memory added, the motivating premise updated for native auto memory, the OKF claim tempered to what the spec actually is, several competitor cells corrected, and Claude Cowork support moved from a present-tense claim to deferred future work.
- Glossary extended with the operations and mechanics the design now names: forget and redact, session digest, reindex, project id, origin and scope, registry, marker, pinned, cap, judgment rules, tombstone.
- ADRs 0001–0004, 0006 and 0008 amended for consistency with the review's decisions: sanctioned explicit recall widening, corrected OKF attribution, security note on store syncing, pointers to the new trust and scope ADRs, the settled invocation mechanism, and pinned project-identity mechanics.
- `AGENTS.md` now also references the OKF profile.

## [0.1.0] – 2026-07-11

### Added

- Initial release.

[Unreleased]: https://github.com/Kntnt/Mimer/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Kntnt/Mimer/releases/tag/v0.1.0
