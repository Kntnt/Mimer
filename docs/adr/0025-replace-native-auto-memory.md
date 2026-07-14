# Replace Claude Code's native auto memory, per project, warned and assisted

Supersedes ADR 0019. That decision had Mimer *coexist* with Claude Code's native auto memory and merely recommend disabling it. Running both is not benign: the native memory keeps its own copy of what it captures, so a fact you forget or redact in Mimer can be re-injected by the native one — a hole in requirement 4 (what is forgotten must stay forgotten). Mimer therefore replaces native memory rather than coexisting with it. The native feature is controlled by `autoMemoryEnabled`, settable per project in `.claude/settings.json`; disabling it there reaches neither the user's other projects nor Claude's chat and Cowork memory, which are separate systems — so the recommendation is the project-scoped switch, not a global one. Mimer detects the setting at session start and, while native memory is on, emits a **warning** — not a mild notice, because a forgotten fact can silently return — pointing to a `disable-native-memory` command that writes the project-scoped setting. Mimer never flips it silently, since writing a user's config unbidden is invasive. The README states the recommendation plainly and early. Verification gates continue to assert on Mimer's own artefacts — hook output, store contents, index results — never on model behaviour native memory could satisfy on its own.

## Considered Options

- **Coexist and softly recommend disabling** (ADR 0019) — rejected now: it leaves the forgetting hole and two divergent memories injecting at every start.
- **Silently disable native memory on install** — rejected: an invasive config mutation without consent.
- **Replace it: detect, warn, and assist a project-scoped disable the user confirms** (chosen).

## Consequences

- The confidentiality and forgetting guarantees hold against Mimer's own store; the warning is what stops native memory quietly undermining them.
- A `mimer-manage disable-native-memory` command and the SessionStart warning are build items (Stages 5c, 8).
