# Model stack: local embeddings, Claude Haiku for generation

Embeddings for semantic search run on a local, lightweight model (an ONNX-based Python library, no external service), because Anthropic offers no first-party embeddings API and an external embeddings API would mean a new subscription — which the "no new infrastructure" principle rules out. Summarisation and distillation, which can reuse the agent's existing Claude access, use Claude Haiku. The rule: reuse Claude where possible (generation); keep it local and light where Claude cannot help (embeddings).

## Considered Options

- **An embeddings API (Voyage, OpenAI, Cohere)** — better quality, rejected: a new subscription, against the no-new-infrastructure principle.
- **A local embedding service such as Ollama** — rejected: a new runtime/daemon.
- **A local ONNX embedding library plus Claude Haiku for generation** (chosen).

## Consequences

- Embedding quality is "good enough, locally", not best-in-class; acceptable under "start simple".
- Switching the embedding model forces a full re-embed — routine rather than disastrous, because the index is derived and rebuildable (ADR 0011).
- "The agent's existing Claude access" is not directly reachable from a detached hook process; ADR 0009 settles the concrete invocation mechanism (LLM-free capture, one guarded batched call per session, no API key).
