# Automated distillation; AI-native, minimal deviation

Mimer is AI-native: it stays close to established AI knowledge tools (retrieval by meaning, cited recall, self-organising notes) and deviates deliberately in only two ways — using the Open Knowledge Format instead of an app-specific store, and the three-layer memory model. Distillation from memory into permanent knowledge is therefore automatic and agent-driven, not gated by human review; trust is earned the AI-native way, through provenance and citations on recall rather than up-front approval. The model unifies Hermes' memory mechanism (short- and long-term) with the second-brain permanent layer, and the automated distillation that bridges them is Mimer's distinctive contribution. Ungated does not mean unguarded: ADR 0014 adds the trust boundary (memory is data, not instructions; confirmed pinned writes; announced injection), ADR 0013 the confidentiality scope, and ADR 0015 the read-modify-write semantics that keep automatic curation from contradicting itself.

## Considered Options

- **Human-review-gated curation** — rejected as not AI-native and too high-friction; the value of an agent second brain is that it curates itself.
- **Automatic, agent-driven distillation, with citation-based trust** (chosen).
