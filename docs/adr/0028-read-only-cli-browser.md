# A read-only CLI browser for the store

The memory must be readable without starting a Claude session. Mimer adds a small, strictly read-only browser in the `mimer` command family: it searches the whole store with the same hybrid index recall uses — local embeddings, no model call, no network — pages through the hit list, and reads a chosen hit as paginated text with its source and date shown. It performs no writes: no remember, no forget, no redact, so it can never damage the store. It reads across every scope without filtering, because scope protects clients from each other in the agent's recall, not the user from their own memory — and full sight is the point, since this is also where the user audits, with their own eyes, what has become global (ADR 0027) and what a project remembers. The tool carries two requirements directly: requirement 5 (knowledge is usable, and now searchable, without the agent) and requirement 2 (verifiability, since one can inspect what memory believes without going through the model being checked).

## Considered Options

- **Inspection only through the in-session skill** — rejected: it requires an agent and routes verification through the very model whose memory is under review.
- **A read-only CLI browser sharing recall's index** (chosen).

## Consequences

- It reuses the recall index rather than a second search path (DRY); the in-session inspection surface (Stage 5c) and this browser share one search implementation.
- Being read-only and scope-blind, it is the natural audit surface for the leakage guard; the choice of TUI technique is left to the build.
