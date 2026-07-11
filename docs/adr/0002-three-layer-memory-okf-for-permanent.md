# Three memory layers; OKF for permanent memory only

Mimer has three layers: short-term memory (the capped snapshot injected each session), long-term memory (the raw, append-only session record) and permanent memory (the global, curated body of atomic, linked Concepts — the second brain). Only permanent memory uses the Open Knowledge Format (OKF); short-term and long-term memory are plain Markdown. OKF is a format for curated knowledge Concepts and, by its own specification, not for raw logs — so applying it to the snapshot or the record would misuse the format and blur the line between recorded memory and curated knowledge.

## Considered Options

- **Everything in OKF** (the first assumption) — rejected: the snapshot is mutable state and the record is raw; neither is a curated Concept.
- **Two layers only** (short- and long-term), as in Hermes — rejected: nothing accumulates durable curated knowledge, so the result is an agent memory, not a second brain.
- **Three layers, OKF for permanent memory only** (chosen).
