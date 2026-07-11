# Snapshot lifecycle: injected once per context lifetime; the files stay live

"Frozen for the session" needs a precise meaning, because the SessionStart hook fires on startup, resume, clear and compact — not only on a fresh launch — and the memory skill reads and writes the live files mid-session. The rule: the snapshot is injected once per context lifetime, and Mimer re-injects deliberately on every SessionStart source, including compact — a compacted context would otherwise lose its memory mid-conversation. "Frozen" means the agent never spontaneously re-reads memory mid-context: between injections, its picture changes only through the memory skill, which is the sole mid-session interface to the live files. Snapshot entries are date-stamped and injection labels their age, so a pending decision from three weeks ago reads as three weeks old, not as current truth.

## Considered Options

- **Inject only on startup and filter out compact/resume** — rejected: the post-compact context would lose the snapshot entirely, exactly when a long session needs memory most.
- **Live re-injection whenever the files change** — rejected: the agent's picture of what is true would shift mid-conversation without signal, and concurrent sessions would bleed into each other.
- **One injection per context lifetime, deliberate re-injection on compact, live files behind the skill** (chosen).
