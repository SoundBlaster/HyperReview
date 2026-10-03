# Product specification

## Goal and scope

Help a reviewer understand what a PR changes about product responsibilities,
where that explanation comes from, and what remains uncertain. The pilot runs
on the operator's MacBook and reads explicitly allowlisted GitHub repositories.

**HR-PROD-001 — Bounded explanation.** The reviewer MUST explain a selected
architectural slice of the PR. It MUST report the actual source scope and any
omitted, unsupported, binary, or truncated input. It MUST NOT claim exhaustive
coverage when only changed files and selected surroundings were inspected.

**HR-PROD-002 — Paired projection.** Output MUST include valid before/after
`.hc` projections, a readable structural diff, source references, and a concise
explanation. Both projections MUST share an identity mapping and abstraction
profile. Unchanged responsibilities MUST retain IDs. Execution order and
arbitrary call/dependency edges MUST NOT be invented through tree nesting.

**HR-PROD-003 — Evidence status.** Claims MUST distinguish `declared`,
`resolved`, `observed`, and `inferred`. Missing evidence MUST remain `unknown`;
it is not proof of either compliance or violation. A passing test or resolved
configuration value MUST NOT be presented as proof of all execution paths.

**HR-PROD-004 — Local first.** Default delivery MUST be a local preview. The
MVP MUST NOT submit a GitHub approval, request changes, modify source code,
resolve review threads, or merge a PR. A separately enabled publication mode
may maintain one ordinary explanatory comment per PR.

**HR-PROD-005 — Architecture sources.** If accepted Hypercode architecture is
supplied, its revision and authority MUST be recorded separately from inferred
projections. The reviewer MUST NOT rewrite accepted intent to match code.
The first pilot does not require SpecGraph integration or a conformance engine.

**HR-PROD-006 — Useful quiet behavior.** Changes with no supported architecture
finding MUST produce a short explanation of that outcome, not an invented
structural change. A documentation-only PR may legitimately have identical
before/after projections. A skipped analysis MUST state why it was skipped.

## Proposed first demonstration

Select a small set of SpecGraph PRs covering responsibility extraction,
refactoring without architecture change, a changed constraint, documentation,
and an intentionally introduced violation in a controlled fixture. The chosen
PRs and code language must be recorded before evaluating results.

## Non-goals for the MVP

Full-codebase reverse engineering, automatic architecture adoption, automatic
code repair, execution-trace reconstruction from static structure, and automatic
verdicts about correctness are outside the initial pilot.
