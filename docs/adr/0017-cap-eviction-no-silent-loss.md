# The cap: promote-then-evict, and eviction is itself a write

"Nothing is dropped silently" must hold mechanically, not by assumption. When a write would exceed the short-term cap, the sequence is promote-then-evict: a durable item is evicted only after its promoted Concept is verified on disk; if promotion fails, the entry stays over-cap and the failure is surfaced, never swallowed. Transient items age out — but ageing out is itself a write: the evicted entry is appended verbatim to today's daily log under an aged-out heading and indexed, so the guarantee no longer depends on the hope that a lossy capture summary happened to include the same detail. Until capture exists (it is built in Stage 3), the cap only warns and nothing is evicted, because neither destination exists yet.

## Considered Options

- **Evict on overflow and trust that evicted items "already live in long-term"** (the first cut) — rejected: capture bullets are lossy and fire-and-forget, so the claim is only probabilistically true — which is to say, false as a guarantee.
- **No cap** — rejected: an unbounded working set defeats the snapshot's purpose and removes the engine that feeds distillation.
- **Promote-then-evict with eviction-as-write, and warn-only before the destinations exist** (chosen).
