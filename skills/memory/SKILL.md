---
name: memory
description: >-
  Curated writes to Mimer's memory. Use when the user asks to "remember" or
  "note that" something worth keeping, or to "forget about" something. Reads the
  whole of short-term memory first, then adds, replaces or removes an entry with
  a one-line echo. "forget" is the soft tier: it removes and tombstones, leaving
  the raw record intact.
---

# Memory — curated writes

This skill records what the user explicitly asks Mimer to keep, change or drop.
It never hand-edits the store; it drives the deterministic engine
`mimer-memory`, which reads short-term memory first (so a repeat never
duplicates), writes under the per-project lock, and returns the exact one-line
echo to relay to the user.

## Trigger phrases

Act when the user's message carries an explicit memory intent:

- **Remember** — "remember that …", "remember to …", "keep in mind …".
- **Note that** — "note that …", "make a note …", "for the record …".
- **Forget about** — "forget about …", "drop …", "you can forget …".

A passing mention of the word "remember" is not a request to write memory. Only
act when the user is clearly asking Mimer to store or drop something.

## How to perform a write

Run the engine from the project's working directory and relay its echo verbatim:

```bash
uv run --project "${CLAUDE_PLUGIN_ROOT}" mimer-memory remember "the fact, in the user's own terms"
uv run --project "${CLAUDE_PLUGIN_ROOT}" mimer-memory note     "the note"
uv run --project "${CLAUDE_PLUGIN_ROOT}" mimer-memory forget   "the fact to drop"
```

Pass the fact as a single, self-contained sentence — one claim per write, phrased
so it still makes sense read cold in a later session. The engine dedups, so
re-remembering an existing fact updates it in place rather than adding a copy.

## Judgment rules (editable)

These rules decide *whether* and *how* to write. They are prose on purpose: read
them, question them, tune them to the user — no code change required (ADR 0018).

### Salience — is it worth keeping?

Keep decisions, preferences, constraints, commitments and hard-won facts that a
future session would benefit from. Do **not** store transient chatter, things
trivially re-derivable from the code, or secrets the user pasted in passing
(credentials, tokens, private keys) — those are for redaction, never memory.

### Durability — short-term now, permanent later

Everything this skill writes goes to short-term memory. Durable, reusable
knowledge is promoted to permanent memory automatically by distillation later;
you do not file it by hand. If the user says a fact is "always" true about them
or asks you to "always remember" it, tell them that is a profile/pinned write,
which arrives with permanent memory — do not fake it here.

### "forget about X" — delete or defer?

"forget about X" is ambiguous, and the difference matters:

- **Defer** — "forget about the refactor **for now**", "let's set X aside",
  "park X" mean *stop working on it*, not *erase it*. Do **not** call
  `forget`; acknowledge and move on.
- **Delete** — "forget that I said X", "drop the note about X", "you can forget
  X" mean remove it from memory. Call `mimer-memory forget "X"`.

When it is genuinely unclear, ask which they mean before deleting. `forget` is
the soft tier: it removes and tombstones so the fact will not resurface, but the
raw long-term record stays. Erasing that record is `redact`, a separate,
explicit action.

### Confirmation

Echo every write back to the user in one line (the engine returns it). If a write
would exceed the short-term cap, the engine warns; relay that too. Nothing is
silently dropped.
