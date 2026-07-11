# Judgment rules are editable prose, not hardcoded logic

The rules for what is worth keeping — salience thresholds for capture, what counts as durable versus transient at the cap, the confidentiality classification of ADR 0013, the instruction-content rejection of ADR 0014, and disambiguation of trigger phrases such as "forget about" — live as prose instructions inside the memory skill, versioned with the plugin and editable by the user. Judgment is the part of a memory system most likely to be wrong for a given person, so it must be readable, questionable and tunable without touching code.

## Considered Options

- **Judgment encoded in code** — rejected: opaque to the user, and every tuning becomes a release.
- **Judgment rules as editable prose in the skill** (chosen).
