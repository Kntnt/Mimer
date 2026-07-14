# The session pass distils straight from the raw record, detached

Refines ADR 0009, whose core stands: capture is LLM-free, the model runs as one guarded, batched Claude Haiku call per session behind the re-entrancy guard, and no API key is ever stored. Two specifics change. First, the batched pass no longer writes a separate *session digest* into long-term memory as an intermediate step; it distils straight from the raw captured record — refreshing short-term's auto-maintained sections and promoting durable facts into Concepts in one pass. The raw long-term log stays raw, because the real summarisation is the distilled Concept; an intermediate prose summary duplicated distillation and bought a nicer-reading log at the cost of a moving part. Second, the pass is spawned **detached**, like capture, so it never delays session close; because distillation is idempotent per fact, a detached pass killed mid-run simply retries at the next boundary. A manual **"distill now"** verb triggers the same pass on demand, so a long or parallel session can publish its findings to other sessions without waiting for the boundary — and, since the user is present, any sensitive-scope consent (ADR 0027) is resolved in the moment rather than deferred.

## Considered Options

- **Digest then distil, run inline at session end** (ADR 0009 as first built) — rejected now: the digest is an intermediate summary distillation subsumes, and an inline pass can lag a long session's close.
- **Distil straight from the raw record, detached, plus an on-demand trigger** (chosen).

## Consequences

- Long-term memory is the raw extractive record only; there is no abstractive digest layer between it and the Concepts, and the reranker's "session digest" source weight becomes moot and collapses toward recency alone.
- Distillation reading the raw record is what makes a crash-orphaned session recoverable: its captured turns are distilled at the next boundary, deduplicated per fact (ADR 0015), so they are neither lost nor duplicated.
