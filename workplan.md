# HyperReview implementation workplan

**Current delivery:** specifications, a parsable desired-system Hypercode model,
and a manual Python pipeline through filtered requests, Codex inference,
and compiled paired projections with local Markdown output and metadata-only
MLflow delivery. Six controlled pilot cases and local Evidently reports are
implemented, with explicit sanitized report export to local MLflow. Local feedback,
read-only publication planning, and a one-shot publisher implementation are
present; local verification, review and the explicitly authorized live pilot remain.

| Phase | Work | Exit evidence |
|---|---|---|
| P0 — Specification | Agree scope, IDs, data contracts, and provider/delivery profiles | Specification PR; validated `.hc`/`.hcs`; decisions on initial language and model |
| P1 — Manual preview | Implement PR eligibility, pinned evidence collection, paired projection, artifact validation, Markdown output, and local MLflow tracking | One real SpecGraph PR explained locally; acceptance fixtures for evidence, identity, and trust boundaries |
| P2 — Own-PR feedback | Let a user mark a preview for their own PR `ok` or `not_ok`, with an optional note | Feedback is associated with the exact PR revisions and projection version; technical fixtures and reports remain separate |
| P3 — Controlled publishing | Implement the authorized one-shot publisher in gated increments; do not couple it to polling | Local gates and recovery pass; separately authorized test PR receives one correct comment |
| P4 — Local worker | Run only the proven one-shot path under `launchd` | Serialized polling, wake/restart recovery, resource bounds, logs and retention verified |

MLflow `3.16.1` is installed in an isolated optional runtime; its local SQLite
delivery and loopback UI have been exercised. The local Evidently reporting
subset uses a separate optional Python 3.12+ runtime. Intake uses Python 3.10+
standard library, the pinned SpecificationCore policy package and `gh`.
SpecGraph PR #761 is the first intake smoke case. Its selected slice was analyzed
with the existing local LM Studio gpt-oss-20b model, explicit API alias and context
16384. The alias fingerprint is recorded; a weights revision remains unavailable.
Unattended Codex isolation and controlled publishing remain open. Comparative accuracy or
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
   The dry-run is complete. Controlled publishing is the next implementation
   phase; it must remain a separate, explicitly invoked path.
## P3 implementation increments

1. One-shot publication with reviewed artifact digests, explicit repository/mode
   authorization, per-PR serialization, narrow comment writes, recovery receipts
   and stale-after-write handling: [contract](SPECS/20-controlled-publication.md).

## P3 — Controlled publishing stages

1. **P3.1 — One-shot broker gate and write (implemented locally).** Add an explicit `publish` command
   that binds the exact saved plan and comment to operator-reviewed digests and
   an exact repository/mode authorization. Re-read the artifacts, require a
   ready plan and confirmed tracking, then recheck authenticated account, PR
   eligibility, base/head/merge-base, and marked-comment inventory immediately
   before writing. Serialize writers per repository/PR. The command may create
   or update only the single HyperReview-owned marked comment; it never approves,
   merges, pushes, or resolves review threads.
2. **P3.2 — Idempotency and uncertain-response recovery (implemented locally).** Persist a small
   redacted operation receipt before/after the remote write. On timeout or
   restart, find the unique marker and reconcile its comment ID and body before
   retrying; never blindly append a second comment. Reject duplicate owned
   markers and preserve a recoverable pending state.
3. **P3.3 — Post-write race handling (implemented locally).** Recheck PR eligibility and revisions
   after the write. If revisions moved, mark that same comment stale and record
   a refresh-needed receipt; never claim it is current. Confirm exact body/ID
   for create and update paths.
4. **P3.4 — Authorized pilot.** Only after P3.1–P3.3 and CI pass, the operator
   reviews the exact compact preview and authorizes one designated SpecGraph
   test PR. Verify one comment, safe update/retry, stale revision, tracking
   gate, and zero unintended GitHub writes.

## P4 — Local worker stages

1. Wrap the proven one-shot pipeline in a `launchd` job with one active lease
   per PR, a bounded queue, explicit allowlist, and no automatic provider
   fallback.
2. Verify sleep/wake and restart recovery, bounded retries/timeouts, resource
   limits, and sanitized log/receipt retention.
3. Enable unattended operation only after the operator reviews the launch
   configuration and the P3 pilot evidence. Scheduler execution cannot grant
   publication authorization by itself.

**Current step:** P3.1–P3.3 are implemented on the current feature branch; the
full local suite passes. CI and review are next. P3.4 must wait for a separate
explicit approval of one concrete SpecGraph plan; no live GitHub write was used
for development verification.

A later optional phase may compare explicit SpecGraph architectural intent
against source-derived evidence. It must preserve accepted intent and inferred
projections as separate artifacts and cannot assume graph-shape equality.

Current inference increment: composition-v4 paired-side instructions and one
bounded validation regeneration, with fixed diagnostic codes and per-attempt
metadata. This does not add a durable failed-job journal or unattended worker.

Explanation increment: composition-v6 domain responsibility explanations,
with explicit separation of code changes and comment descriptions. Evaluate
the actual local-model output; structural validity alone is insufficient.
The local gpt-oss-20b pilot still produces generic nodes after regeneration.
This failure prompted the selected Codex pilot below; passing fixture/transport
tests alone does not establish explanation quality.

Selected pilot path: direct Codex CLI generation, `gpt-6-luna` with reasoning
`low`, after a successful isolated probe on PR #769's selected source pair.
The common compilation/tracking pipeline is retained; generic model adapters
are deferred. [Invocation contract](SPECS/18-codex-generation.md).
The integrated default path generated a locally valid plan in one attempt on
the same PR #769 source pair, correctly distinguishing a comment change from
unchanged comparison code and marking external catalog behavior unavailable.
The paired Hypercode projections passed the real compiler and metadata-only
MLflow delivery was confirmed. This is one observed slice, not a general model
quality claim. Next: exercise the publication dry-run using this compiled bundle.

Project quality integration: one behavior-preserving PR metadata eligibility
Specification backed by SpycificationCore; pinned SpecificationMetrics collection
of application S/U and Python LOC/CC/Cog. CI and local SQLite snapshots retain
scope/status rather than introducing a composite score or quality threshold.
See [contract](SPECS/19-specification-quality.md).
