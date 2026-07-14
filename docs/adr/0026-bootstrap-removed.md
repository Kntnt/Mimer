# Bootstrap (import of pre-existing history) is removed

The staged plan carried a bootstrap stage: a per-project import that walked existing Claude Code session history, extracted meaningful turns, and seeded memory with a first distillation pass. It is removed. Bootstrap hung on parsing Claude Code's session transcript format, which is vendor-internal, undocumented and changes between releases — an adapter that cannot be future-proofed — and it carried none of the five requirements: it fills memory faster at first run but adds nothing to confidentiality, verifiability, distillation, forgetting or portability. Mimer starts from zero and fills forward through capture and distillation. This is the template the whole slimming followed: however well an adapter could be built, a mechanism that bears no requirement and depends on an unstable external format is cut.

## Considered Options

- **Keep bootstrap** — rejected: it bears no requirement and depends on an undocumented, shifting transcript format.
- **Remove bootstrap; start from zero and fill forward** (chosen).

## Consequences

- There is no import stage; the first run of a project has empty memory that capture and distillation fill going forward.
- Forward transcript *archiving* is unaffected: it copies the transcript file as opaque provenance and does not parse it, so it does not inherit bootstrap's fragility.
- Git history is likewise not backfilled; the `git:<sha>` citation convention (ADR 0021) anchors entries to commits as they are referenced, not by bulk import.
