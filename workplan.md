# HyperReview implementation workplan

**Current delivery:** specifications, a parsable desired-system Hypercode model,
and a manual Python evidence-intake CLI. This is the first P1 increment; paired
projections, tracking, evaluation, scheduler, and publishing are not implemented.

| Phase | Work | Exit evidence |
|---|---|---|
| P0 — Specification | Agree scope, IDs, data contracts, and provider/delivery profiles | Specification PR; validated `.hc`/`.hcs`; decisions on initial language and model |
| P1 — Manual preview | Implement PR eligibility, pinned evidence collection, paired projection, artifact validation, Markdown output, and local MLflow tracking | One real SpecGraph PR explained locally; acceptance fixtures for evidence, identity, and trust boundaries |
| P2 — Pilot evaluation | Prepare 5–10 cases and compare reviewer outcomes | MLflow dataset/run/assessment records; Evidently JSON/HTML reports for matched cases with limitations |
| P3 — Controlled publishing | Implement explicit authorization, marked-comment upsert, revision checks, deduplication, and recovery | Authorized test PR receives one comment; stale/race/retry and MLflow-delivery-gate scenarios pass |
| P4 — Local worker | Install a `launchd` job using the proven one-shot path | Serialized polling, wake/restart recovery, resource bounds, logs and retention verified |

MLflow and Evidently are selected; their installation and integration remain
implementation work. Intake uses Python 3.10+ standard library and `gh`.
SpecGraph PR #761 is the first intake smoke case. The exact local model, Codex
isolation mechanism, and evaluation corpus remain open; choose and record these
before model analysis. Executable presence alone does not choose a backend.

## P1 increments

1. Evidence intake: implemented; [scope and limitations](SPECS/08-intake-milestone.md).
2. Next: provider-neutral request/result schema and a credential-free, content-filtered
   model input boundary. Verify a configured local HTTP backend.
3. Paired Hypercode projection, identity/provenance validation, and explanation.
4. Local MLflow tracking and bounded recovery; complete P1 acceptance fixtures.

A later optional phase may compare explicit SpecGraph architectural intent
against source-derived evidence. It must preserve accepted intent and inferred
projections as separate artifacts and cannot assume graph-shape equality.
