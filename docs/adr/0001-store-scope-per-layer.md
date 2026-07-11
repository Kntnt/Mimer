# Single physical store; memory scoped per project, permanent memory global

Mimer keeps everything in one physical store on the machine, not scattered into project repositories. Logical scope differs by layer: short-term and long-term memory are project-scoped (keyed by a derived project id), while permanent memory is global. This keeps durable knowledge recallable across every project — the point of a second brain — while raw session memory stays tied to the work it came from, and the store stays portable and free of the projects' own version control.

## Considered Options

- **A separate store per project** — silos knowledge and scatters memory into repos, polluting their history and losing cross-project knowledge.
- **One global store with the project as a mere tag on everything** (the first cut) — but raw memory is not cross-cutting; only distilled knowledge is, so global-by-default recall over raw logs is noise.
- **One physical store, scope per layer** (chosen) — memory per project, permanent memory global.

## Consequences

- Injection = the current project's short-term memory plus the pinned global profile.
- Recall = the current project's long-term memory plus all permanent memory; cross-project value travels through distillation into permanent memory, not through raw logs.
