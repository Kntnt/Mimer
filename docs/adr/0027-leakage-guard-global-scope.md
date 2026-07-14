# A consent guard on promotion to global scope

Refines ADR 0013. That decision made scope client-safe by default — project is the default, global is earned by client-neutrality — but the classification is entirely the model's judgment, and for an NDA that is not enough to keep client identities, business facts and contract terms from becoming global. This adds a two-tier guard at the moment a Concept would be promoted to global scope. Content the judgment rules classify as **sensitive** — client identities, business facts, terms, anything behind an NDA — is never promoted to global without the user's **explicit consent**. Because distillation runs unattended at session boundaries, the consent question is posed at the next session start and the content waits, project-bound, until answered; the safe state is therefore also the waiting state, so an unanswered consent can never leak. When the user triggers distillation manually ("distill now", ADR 0023) they are present, so the consent is resolved in the moment. Everything else is promoted automatically as before — 0% effort preserved — but every new global Concept is **announced** at the next session start and can be demoted to project scope or forgotten with one command. The sensitivity rules live in the editable judgment rules (ADR 0018), and the guard is deliberately minimal: one question, one answer, no policy engine.

## Considered Options

- **Automatic global promotion on the model's classification alone** (ADR 0013) — rejected as insufficient: an NDA needs more than the model's judgment before client facts travel.
- **Confirm every global promotion** — rejected: it destroys the 0%-effort promise for the common, safe case.
- **Sensitive requires consent (default is waiting); the rest is announced and reversible** (chosen).

## Consequences

- A verifiable gate: a sensitive fact awaiting consent must never appear in widened recall from another project, and must not be promoted to global until consent is given (Stage 5b).
- The announcement of new global Concepts, with a one-command reversal, is the audit-and-undo path; the read-only CLI browser (ADR 0028) is where the user inspects, with their own eyes, what has become global.
