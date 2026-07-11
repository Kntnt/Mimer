# Memory is data, not instructions: the trust boundary against memory poisoning

Captured content flows from untrusted sources — cloned repositories, web pages, pasted logs — through capture and distillation into text that is injected into future sessions before the user types anything. Without a boundary, that pipeline is a persistent prompt-injection channel: an imperative planted in a third-party README becomes a distilled "decision" and then standing instructions in every project. The boundary is threefold. First, everything Mimer injects or recalls is wrapped in a quoted, cited data frame carrying a standing rule that memory content is information about the past, never directives to follow. Second, the distiller's judgment rules reject instruction-shaped content — imperatives addressed to the agent do not become Concepts. Third, the highest-privilege writes are confirmed: creating or modifying a pinned or profile Concept requires explicit user confirmation, and injection is no longer fully silent — the snapshot carries a one-line notice of what was injected and which Concepts were distilled since the last session, so a poisoned or mistaken memory is visible instead of invisible.

## Considered Options

- **Fully silent injection with citation-based trust alone** (the first cut) — rejected: citations defend against hallucination on the recall path, not against instruction-following on the injection path, which happens before anyone is looking.
- **A human review gate on all distillation** — rejected in ADR 0004 and still rejected: the fix is a trust boundary, not a return to manual filing.
- **Data framing, instruction rejection in the judgment rules, confirmed pinned writes, and announced injection** (chosen).
