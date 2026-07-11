# Recall is an agent-invoked tool, not always-on retrieval

Recall is exposed as a tool the agent calls when it judges it needs context — the same tool also serves an explicit user question — rather than an always-on step that augments every turn automatically. This keeps injection (deterministic, at session start, frozen) cleanly separate from recall (on demand, mid-session), and avoids bloating the context window, paying a retrieval cost on every turn, and undermining the frozen snapshot. Always-on auto-augmentation is deliberately deferred as a later, tunable option, not the default.

## Considered Options

- **Always-on retrieval augmentation** (auto-search every turn, as in some AI note tools) — rejected as the default: context bloat, per-turn cost, and conflict with the frozen snapshot.
- **Agent-invoked recall tool, plus explicit user command** (chosen).
