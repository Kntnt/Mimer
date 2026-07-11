# Permanent memory is scoped by origin: global for client-neutral knowledge only

Automatic distillation into an unconditionally global layer is a cross-client leakage machine for anyone who serves multiple clients from one machine: a fact learned in client A's project would surface, cited to client A, while pairing with client B. Every Concept therefore records its **origin** (the project it was distilled or written from) and a **scope**. Distilled Concepts default to their origin project's scope — recallable there, invisible elsewhere. Only what the judgment rules classify as client-neutral — the user's own preferences and profile, general techniques, tooling knowledge — is promoted with global scope, and the user can widen or narrow a Concept's scope explicitly. Profile Concepts are global by definition. Per-project settings control the boundary: capture on or off, distill-to-global on or off, and participation in widened recall; a session-level "pause capture" covers the throwaway case. This refines ADR 0001: the store stays single and permanent memory remains the one durable cross-project layer, but a Concept travels across projects only when its content is safe to travel.

## Considered Options

- **Permanent memory unconditionally global** (ADR 0001's first reading) — rejected: confidentiality boundaries between projects are real, and the design's advertised success criterion (cross-project surfacing) is also its worst failure mode.
- **A separate store per client** — rejected: re-introduces the silos ADR 0001 rejected, and clients are not always known at capture time.
- **One store; Concepts carry origin and scope; global is earned, not default** (chosen).

## Consequences

- Recall enforces scope: project-scoped Concepts never appear outside their origin, regardless of widening.
- The judgment rules gain a confidentiality classification, editable like the rest (ADR 0018).
- The second-brain promise narrows honestly: what follows you across projects is your knowledge, not your clients'.
