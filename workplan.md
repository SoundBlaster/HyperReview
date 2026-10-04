# HyperReview implementation workplan

**Current delivery:** specifications, a parsable desired-system Hypercode model,
and a manual Python pipeline through filtered requests, local HTTP inference,
and compiled paired projections with local Markdown output and metadata-only
MLflow delivery. Six controlled pilot cases and local Evidently reports are
implemented, with explicit sanitized report export to local MLflow. Human
comparison, scheduler, and publishing remain open.

| Phase | Work | Exit evidence |
|---|---|---|
| P0 — Specification | Agree scope, IDs, data contracts, and provider/delivery profiles | Specification PR; validated `.hc`/`.hcs`; decisions on initial language and model |
| P1 — Manual preview | Implement PR eligibility, pinned evidence collection, paired projection, artifact validation, Markdown output, and local MLflow tracking | One real SpecGraph PR explained locally; acceptance fixtures for evidence, identity, and trust boundaries |
| P2 — Pilot evaluation | Prepare 5–10 cases and compare reviewer outcomes | MLflow dataset/run/assessment records; Evidently JSON/HTML reports for matched cases with limitations |
| P3 — Controlled publishing | Implement explicit authorization, marked-comment upsert, revision checks, deduplication, and recovery | Authorized test PR receives one comment; stale/race/retry and MLflow-delivery-gate scenarios pass |
| P4 — Local worker | Install a `launchd` job using the proven one-shot path | Serialized polling, wake/restart recovery, resource bounds, logs and retention verified |

MLflow `3.16.1` is installed in an isolated optional runtime; its local SQLite
delivery and loopback UI have been exercised. The local Evidently reporting
subset uses a separate optional Python 3.12+ runtime. Intake uses Python 3.10+
standard library and `gh`.
SpecGraph PR #761 is the first intake smoke case. Its selected slice was analyzed
with the existing local LM Studio gpt-oss-20b model, explicit API alias and context
16384. The alias fingerprint is recorded; a weights revision remains unavailable.
Codex isolation and the human evaluation corpus remain open. Executable presence
alone does not choose a backend.

## P1 increments

1. Evidence intake: implemented; [scope and limitations](SPECS/08-intake-milestone.md).
2. Provider-neutral request/result schema and a content-filtered model input
   boundary: [contract](SPECS/09-model-contract.md). LM Studio/Ollama transport:
   [local inference](SPECS/10-local-inference.md), with offline fixtures and a
   controlled local readiness probe.
3. Paired Hypercode compilation, identity/provenance validation, and explanation:
   [compiled preview](SPECS/11-compiled-preview.md).
4. Local MLflow tracking and bounded recovery:
   [delivery profile](SPECS/12-local-tracking.md), exercised on the compiled real slice.
5. Controlled versioned cases and sanitized local Evidently reports:
   [pilot subset](SPECS/13-pilot-boundaries.md) and [local evaluation handoff](SPECS/14-evaluation-handoff.md).
   Next: independent human comparison on matched real cases. Evaluation delivery
   has no durable retry outbox yet.

A later optional phase may compare explicit SpecGraph architectural intent
against source-derived evidence. It must preserve accepted intent and inferred
projections as separate artifacts and cannot assume graph-shape equality.
