# Claude access from hooks: LLM-free capture, one guarded batch call per session

A detached hook process is not "the agent" and inherits neither its session nor its credentials, so the model stack of ADR 0006 needs a concrete invocation mechanism. The per-exchange capture path is therefore LLM-free: the Stop hook extracts the exchange from the hook payload and appends lightly condensed extractive bullets — no model call, no latency, no quota. Everything that needs a model — the session digest, the short-term refresh and distillation — runs as one batched Claude Haiku call per session, at session end or at the next opportunity, invoked headlessly through the Claude Code CLI (`claude -p --model haiku`) under a re-entrancy guard: Mimer sets a marker environment variable on every Claude invocation it spawns, and every Mimer hook exits immediately when the marker is present, so a spawned session can never trigger capture of itself. Transcripts of Mimer-spawned sessions are excluded from capture and bootstrap by the same marker. When headless invocation is unavailable, Mimer degrades gracefully: capture stays extractive-only and digest/distillation defer to the next in-session opportunity, where the agent's own Claude access genuinely exists. No API key is ever required.

## Considered Options

- **Claude Haiku per exchange from the Stop hook** — rejected: recursion through Mimer's own hooks, per-turn quota burn on the user's plan, and seconds of latency multiplied by every turn of every session.
- **A stored `ANTHROPIC_API_KEY` for background calls** — rejected: a new paid subscription for subscription-only users, the very cost ADR 0006's own rationale forbids, plus a credential-storage surface in the store.
- **LLM-free capture plus one guarded, batched headless call per session, degrading gracefully** (chosen).

## Consequences

- Long-term memory's per-exchange bullets are extractive, not abstractive; the richer summary arrives with the session digest.
- The re-entrancy guard is load-bearing: every Mimer hook checks it first, and the test harness must cover the nested-invocation case.
- Cost is bounded at one Haiku call per session rather than one per turn.
