# HyperReview implementation workplan

**Current delivery:** specification bootstrap and a parsable desired-system
Hypercode model. No runtime implementation is claimed.

| Phase | Work | Exit evidence |
|---|---|---|
| P0 — Specification | Agree scope, IDs, data contracts, and provider/delivery profiles | Specification PR; validated `.hc`/`.hcs`; decisions on initial language and model |
| P1 — Manual preview | Implement PR eligibility, pinned evidence collection, paired projection, artifact validation, Markdown output, and local MLflow tracking | One real SpecGraph PR explained locally; acceptance fixtures for evidence, identity, and trust boundaries |
| P2 — Pilot evaluation | Prepare 5–10 cases and compare reviewer outcomes | MLflow dataset/run/assessment records; Evidently JSON/HTML reports for matched cases with limitations |
| P3 — Controlled publishing | Implement explicit authorization, marked-comment upsert, revision checks, deduplication, and recovery | Authorized test PR receives one comment; stale/race/retry and MLflow-delivery-gate scenarios pass |
| P4 — Local worker | Install a `launchd` job using the proven one-shot path | Serialized polling, wake/restart recovery, resource bounds, logs and retention verified |

MLflow and Evidently are selected; their installation and integration remain
implementation work. Initial implementation language, exact local model, Codex isolation mechanism,
and first PR corpus remain open. Choose and record these before P1; executable
presence alone does not choose a backend. No scheduler or publisher should be
installed as part of the specification bootstrap.

A later optional phase may compare explicit SpecGraph architectural intent
against source-derived evidence. It must preserve accepted intent and inferred
projections as separate artifacts and cannot assume graph-shape equality.
