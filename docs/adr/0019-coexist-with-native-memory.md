# Coexist with Claude Code's native auto memory; build what it lacks

Claude Code ships native auto memory, on by default since v2.1.59: per-repository notes Claude writes itself, with a `MEMORY.md` index injected at the start of every session and topic files read on demand. That natively covers a real part of Store and Inject, so Mimer neither pretends the gap still exists nor fights the platform. Mimer's position is the layer native memory does not attempt: retrieval by meaning with citations, a curated cross-project permanent layer in an open format with scope and supersession, full-history capture with archived transcripts as provenance, git-log provenance, forget and redact semantics, and bootstrap from pre-existing history. Mimer functions with auto memory left on, but installation guidance recommends disabling it (`autoMemoryEnabled: false`) in Mimer-managed projects to avoid two systems remembering the same things divergently. Verification gates assert on Mimer's own artefacts — hook output, store contents, index results — never on model behaviour that native memory could satisfy on its own.

## Considered Options

- **Ignore native memory** (the docs' original stance, written before checking) — rejected: the premise "Claude Code saves almost nothing unprompted" is now false, and gates phrased as conversation checks would pass with Mimer uninstalled.
- **Require native memory off** — rejected: hostile to users and unenforceable from a plugin.
- **Coexist, recommend disabling in Mimer-managed projects, and differentiate on what native memory lacks** (chosen).
