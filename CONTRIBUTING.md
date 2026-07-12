# Contributing to Mimer

Thanks for considering a contribution. Mimer is open source, so anyone is free to fork it and adapt it for their own purposes. This document describes the *project norm* — what kinds of contribution are likely to be welcomed into the upstream repository at [Kntnt/Mimer](https://github.com/Kntnt/Mimer). It is editorial guidance on what is likely to be merged, not a legal restriction on what you may do with the code.

## Contribution scope

| Category | Examples | Reception |
|---|---|---|
| Welcomed without question | Bug reports; bug fixes against existing behaviour; corrections to broken examples; typo and grammar fixes in prose; clarifications that do not change behaviour. | Open a PR. If the change is small and self-evidently correct, it is usually merged quickly. |
| Accepted but discussed first | New features; changes to existing behaviour, scope, or a public interface; new dependencies. | Open an issue first to align on intent before writing code. A PR without prior discussion may still land, but expect feedback rounds. |
| Unlikely to be merged but free to fork | Changes that alter the project's direction or restructure its architecture in a way that conflicts with its goals. | The licence makes forking explicit and lawful. If you want a different direction, build it in your fork. |

## Inbound licensing

By submitting a contribution, you agree it is licensed under the Apache License 2.0 by virtue of its §5 *Submission of Contributions* — any contribution intentionally submitted for inclusion is under the terms of that licence unless you state otherwise. No separate contributor licence agreement is required.

## Behaviour

Be respectful and constructive in issues, pull requests, and discussions. Assume good faith, keep criticism about the work rather than the person, and help keep this a project people want to contribute to.

## How to contribute

1. **Open an issue first** for anything in the *discussed* row above. For *welcomed* items, you can open a PR directly. Use the issue tracker at <https://github.com/Kntnt/Mimer/issues>.
2. **One concern per PR.** Smaller PRs land faster.
3. **Follow the project's coding standard.** It is materialised under [`agents.d/coding-standard/`](agents.d/coding-standard/) — read `general.md` plus the module(s) for the language or framework you touch before changing code.

## Running the tests

The default suite is fast and needs no external services — run it with `uv run pytest`. It is what CI gates on, and it passes without a live `claude` binary.

Two suites are opt-in because they reach real vendor boundaries, and are skipped unless you opt in:

- **Integration** (`-m integration`, gated on `MIMER_INTEGRATION=1` and a reachable `claude`): drives the real `claude -p --model haiku` call end to end, so a changed CLI flag or wrapped output surfaces as a failure rather than a silent "deferred" degradation. Run with `MIMER_INTEGRATION=1 uv run pytest -m integration`.
- **Packaging** (`-m packaging`, gated on `MIMER_PACKAGING=1`): builds the wheel, installs it into a throwaway virtualenv, and runs the packaged `mimer-*` console scripts and a hook. Run with `MIMER_PACKAGING=1 uv run pytest -m packaging`. CI runs this as its own job.

## Questions

Open an issue or start a discussion. Conversation happens in the open.
