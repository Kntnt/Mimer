# Target platform: Claude Code first; Claude Cowork deferred behind a capability spike

Mimer targets Claude Code alone for the staged build. Claude Cowork runs sessions inside a sandboxed VM isolated from the host machine, so the three things Mimer's design assumes — the host-resident `~/.mimer/` store, access to session transcripts on disk, and headless Claude CLI invocation — are not established to exist there, and hook lifecycle parity with Claude Code is not documented. Cowork support is future work, gated on a capability spike that empirically establishes what a Cowork plugin hook can do (which events fire, filesystem visibility, network egress, model access); the likely first form is a degraded mode (skill-only manual inject and recall, or a store bridge), not a mirror of the hooks. Until the spike passes, no document claims Cowork support in the present tense.

## Considered Options

- **Claim both platforms and assume the Cowork integration "mirrors" the hooks** (the first cut) — rejected: the assumption is unverified, the VM sandbox structurally contradicts the host-store design, and a claim without a stage to build or verify it is marketing, not architecture.
- **Build a dedicated Cowork stage now** — rejected: designing against an unverified platform surface risks a second architecture nobody asked for yet.
- **Claude Code first; Cowork deferred behind a capability spike** (chosen).
