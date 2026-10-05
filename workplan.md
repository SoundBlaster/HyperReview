# HyperReview implementation workplan

**Current delivery:** specifications, a parsable desired-system Hypercode model,
and a manual Python pipeline through filtered requests, local HTTP inference,
and compiled paired projections with local Markdown output and metadata-only
MLflow delivery. Six controlled pilot cases and local Evidently reports are
implemented, with explicit sanitized report export to local MLflow. Local feedback
capture and read-only publication planning are implemented; scheduler and
GitHub comment writes remain open.

| Phase | Work | Exit evidence |
|---|---|---|
| P0 — Specification | Agree scope, IDs, data contracts, and provider/delivery profiles | Specification PR; validated `.hc`/`.hcs`; decisions on initial language and model |
| P1 — Manual preview | Implement PR eligibility, pinned evidence collection, paired projection, artifact validation, Markdown output, and local MLflow tracking | One real SpecGraph PR explained locally; acceptance fixtures for evidence, identity, and trust boundaries |
| P2 — Own-PR feedback | Let a user mark a preview for their own PR `ok` or `not_ok`, with an optional note | Feedback is associated with the exact PR revisions and projection version; technical fixtures and reports remain separate |
| P3 — Controlled publishing | Implement explicit authorization, marked-comment upsert, revision checks, deduplication, and recovery | Authorized test PR receives one comment; stale/race/retry and MLflow-delivery-gate scenarios pass |
| P4 — Local worker | Install a `launchd` job using the proven one-shot path | Serialized polling, wake/restart recovery, resource bounds, logs and retention verified |

MLflow `3.16.1` is installed in an isolated optional runtime; its local SQLite
delivery and loopback UI have been exercised. The local Evidently reporting
subset uses a separate optional Python 3.12+ runtime. Intake uses Python 3.10+
standard library and `gh`.
SpecGraph PR #761 is the first intake smoke case. Its selected slice was analyzed
with the existing local LM Studio gpt-oss-20b model, explicit API alias and context
16384. The alias fingerprint is recorded; a weights revision remains unavailable.
Codex isolation and controlled publishing remain open. Comparative accuracy or
review-time studies are optional research, not release or publication gates.
Executable presence alone does not choose a backend.

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
   Structured generation now converts one model declaration per identity to paired
   Hypercode and emits a compact Russian preview alongside diagnostic receipts:
   [composition plan](SPECS/15-structured-composition.md). A historical four-file
   PR #761 slice passed ordinary local generation and the real compiler without
   a manual rewrite; semantic usefulness is still for the user to assess.
5. Controlled versioned cases and sanitized local Evidently reports:
   [pilot subset](SPECS/13-pilot-boundaries.md) and [local evaluation handoff](SPECS/14-evaluation-handoff.md).
6. Local own-PR `ok`/`not_ok` feedback with optional notes and exact
   revision/projection/preview fingerprints:
   [feedback record](SPECS/16-preview-feedback.md). This captures usefulness,
   without quality thresholds or publication authority.
7. Read-only publication planning with exact preview binding, confirmed tracking,
   current PR eligibility/revisions and marked-comment inventory:
   [dry-run](SPECS/17-publication-dry-run.md).
   Next: authorized comment writes with serialization, post-write checks and
   uncertain-response recovery. Evaluation delivery has no durable retry
   outbox yet.

A later optional phase may compare explicit SpecGraph architectural intent
against source-derived evidence. It must preserve accepted intent and inferred
projections as separate artifacts and cannot assume graph-shape equality.

Current inference increment: composition-v4 paired-side instructions and one
bounded validation regeneration, with fixed diagnostic codes and per-attempt
metadata. This does not add a durable failed-job journal or unattended worker.
