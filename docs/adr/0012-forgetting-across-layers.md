# Forgetting: a two-tier cascade across every layer, with tombstones

A "forget" that removes one short-term entry while the fact survives in the daily logs, the transcripts, the index and a distilled Concept is theatre, so forgetting is defined per layer, in two tiers. **Forget** (the default, soft tier): the entry is removed from short-term memory, any matching permanent Concept is retracted, a tombstone recording the fact's identity is written so distillation never re-promotes it and recall filters it out, and matching index rows are suppressed — but the append-only long-term logs and the unedited transcripts keep the raw record, which the skill states honestly when it confirms the operation. **Redact** (the explicit, hard tier): additionally rewrites the long-term logs and transcripts in place, replacing the span with a redaction marker, and purges and reindexes the affected chunks — the one sanctioned mutation of the otherwise append-only and unedited layers. Redaction also serves the case where a secret was captured before the redaction pass caught it.

## Considered Options

- **Forget as short-term removal only** (the first cut) — rejected: recall by meaning resurfaces exactly what the user asked to forget, cited, and trust in the whole system collapses.
- **Every forget physically purges everything** — rejected as the default: most "forget about X" utterances mean deprioritise, not erase; destroying the raw record by default loses provenance.
- **Two tiers — soft forget with tombstones by default, explicit redact for erasure** (chosen).

## Consequences

- Tombstones are a store artefact: distillation and recall consult them, and they survive reindexing.
- "Forget about the migration for now" no longer destroys data: the soft tier is recoverable from long-term memory.
- The docs state the residual honestly: content already exported or backed up before a redact is beyond Mimer's reach.
