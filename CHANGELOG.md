# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Technical vision and architecture (`docs/vision.md`), including a staged, independently verifiable build plan.
- Domain glossary (`CONTEXT.md`) fixing the project's vocabulary.
- Eight architecture decision records under `docs/adr/`: the store's scope, the three-layer memory model with OKF for curated knowledge, git as a capture source, automated distillation, agent-invoked recall, the model stack, the vector store, and project identity.
- Eleven further architecture decision records (0009–0019), from a multi-lens critical design review: Claude access from hooks, Claude Code first with Cowork deferred, concurrency and the derived index, forgetting across layers, scoped permanent memory, the memory-is-data trust boundary, Concept identity and supersession, the snapshot lifecycle, cap mechanics with no silent loss, editable judgment rules, and coexistence with Claude Code's native auto memory.
- Mimer's OKF profile (`docs/okf-profile.md`): the pinned spec version, the constructs relied on, Mimer's frontmatter extensions, and the fallback stance.
- Foundations (Stage 0): a uv-managed Python project and an installable Claude Code plugin manifest that registers the SessionStart, Stop and SessionEnd hooks.
- Store bootstrap: the `~/.mimer/` store is created on first hook invocation with owner-only permissions (`0700` directories, `0600` files), a `config.toml` and an empty `mimer.log` failure log; the location is overridable via `MIMER_HOME` for isolated testing.
- The re-entrancy guard, so a Claude session Mimer spawns can never trigger Mimer's own hooks and capture itself.
- A pytest harness that drives each hook as a JSON-in/JSON-out subprocess, and a GitHub Actions workflow running ruff, mypy and pytest on every push.
- Project identity: a stable project id resolved from an opt-in `.mimer` marker, the normalised git remote, or the path, backed by a registry that records each project's known remotes and paths. SSH and HTTPS remotes, git worktrees and moved repositories resolve to one id; a marker or remote that would attach a new directory to existing memory is surfaced for confirmation instead of bound silently; adding a remote to a path-keyed project reconciles onto it; and a link/merge action repairs an orphaned project's memory into its recognised identity.
- Concurrency-safe store I/O: a per-project advisory lock guarding read-modify-write of the store's Markdown artefacts — re-reading inside the lock so two concurrent writers never lose an update — plus atomic `O_APPEND` daily-log writes that interleave without corruption, and WAL-mode SQLite connection conventions for the derived index. A lock holder that crashes never deadlocks the store.
- Snapshot injection at session start (Stage 1): the SessionStart hook resolves the project and injects its short-term memory as framed, announced context — data, not instructions — labelling each dated entry with its age. It re-injects on a `compact` source so a compacted context keeps its memory, and an unknown project injects a well-formed empty snapshot. Introduces the fixed short-term memory sections: the auto-refreshed `Active threads` and `Pending decisions`, and the curated `Notes`.

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
