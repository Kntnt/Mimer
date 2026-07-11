# Three memory layers; OKF for permanent memory only

Mimer has three layers: short-term memory (the capped snapshot injected each session), long-term memory (the raw, append-only session record) and permanent memory (the global, curated body of atomic, linked Concepts — the second brain). Only permanent memory uses the Open Knowledge Format (OKF); short-term and long-term memory are plain Markdown. OKF targets curated knowledge concepts — its whole shape (frontmatter'd concept files, a bundle index, citations) suits curated notes; raw session logs and mutable working state fit neither its purpose nor its examples. That is Mimer's design judgment, not a prohibition the spec itself states; either way, applying OKF to the snapshot or the record would blur the line between recorded memory and curated knowledge. Mimer pins the spec version it targets (v0.1, currently a draft) and documents exactly which OKF constructs it relies on, plus its own extensions, in `docs/okf-profile.md`.

## Considered Options

- **Everything in OKF** (the first assumption) — rejected: the snapshot is mutable state and the record is raw; neither is a curated Concept.
- **Two layers only** (short- and long-term), as in Hermes — rejected: nothing accumulates durable curated knowledge, so the result is an agent memory, not a second brain.
- **Three layers, OKF for permanent memory only** (chosen).

## Consequences

- OKF supplies the syntax of permanent memory, not its memory semantics; identity, supersession, pinning, scope and forgetting are Mimer extensions (ADRs 0012, 0013, 0015), recorded in the OKF profile.
- OKF is a young draft from an unofficial repository; the fallback stance is explicit: the files are plain Markdown with YAML frontmatter and remain valid Mimer storage even if the spec changes or dies.
