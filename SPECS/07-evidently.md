# Evidently quality and regression reports

Evidently is the selected local evaluation/reporting library alongside MLflow.
The initial scope is offline reports on versioned pilot cases and assessments;
no Evidently Cloud account or separate monitoring service is required. Package
versions and report formats must be pinned during implementation.

## Evaluation responsibilities

**HR-EVAL-001 — Versioned technical input.** Technical assessments MUST identify
their fixture/dataset version and digest, metric-definition version, and
assessor type. Deterministic compiler, source-ID, provenance, and technical-
quality checks remain distinct from user feedback. A user feedback record is
tied to its own PR's exact base/head revisions and projection version; it is
not a baseline/current comparison. Missing assessments MUST remain missing and
their coverage MUST be reported.

**HR-EVAL-002 — Local technical reports.** Keep per-case outcomes in the local
assessment bundle and produce JSON/HTML reports of technical aggregates for
grammar/reference validity, coverage omissions, structural changes, and
technical latency where available. Use applicable Evidently metrics or
explicitly defined custom metrics over the sanitized assessment table; do not
assume that a built-in metric understands Hypercode or source-code architecture.
Keep user feedback separate from technical metrics. Optional free-text feedback
notes MUST NOT enter the default report. Report IDs and source dataset digests
MUST be included in result metadata.

**HR-EVAL-003 — Regression semantics.** Thresholds and baseline selection MUST
be operator-reviewed and versioned before a comparison is used as a gate.
Technical reports are report-only: a dashboard does not authorize or block
individual GitHub publications. Existing eligibility, artifact, explicit
authorization, tracking-confirmation, and security gates remain authoritative.
Comparative accuracy or review-time research is optional. Changed workload
distributions MUST NOT be reported as model degradation, and small samples MUST
NOT support population-level superiority claims.

**HR-EVAL-004 — Privacy and model calls.** Default reports MUST operate on
sanitized assessment/metric tables and MUST NOT embed source, full prompts,
model-response bodies, or credentials in HTML/JSON or MLflow artifacts.
Text-content metrics require the same explicit repository/destination capture
authorization as HR-TRACK-003. Evidently Cloud uploads, external embedding
services, and LLM judges MUST remain disabled unless separately configured and
authorized. Verify each selected descriptor/metric's data access and inference
behavior before enabling it; a local report process does not imply that every
metric is local. Generation of HTML reports MUST escape untrusted labels/text
and exclude model-supplied scripts or remote resources.

**HR-EVAL-005 — MLflow handoff.** MLflow remains the system for experiment
runs, workflow diagnostics, and assessment lineage. Evidently consumes
versioned technical assessment data and produces report artifacts. The current
explicit handoff logs regenerated sanitized report JSON/HTML, report/dataset
digests, and selected numeric summaries into a separate local MLflow evaluation
run, subject to the report allowance in HR-TRACK-003. Reports containing source-
content-bearing fields MUST NOT use that allowance. Shared metric definitions
MUST have one versioned source of truth; exporting the same assessment through
both tools MUST NOT count as independent evidence or duplicate assessment cases.
The current delivery is not idempotent and has no durable evaluation outbox: a
failure leaves the local report available, while a repeated explicit command
may create another run. It does not invoke the analysis model again.

## Official references

Evidently supports configurable reports, test conditions, local exports, and
custom evaluation. HyperReview supplies the domain definitions and policy above.

- [Evidently repository and report examples](https://github.com/evidentlyai/evidently).
- [Evidently documentation](https://docs.evidentlyai.com/introduction).

The upstream Evidently repository is Apache-2.0 licensed; preserve applicable
license/notice obligations when redistributing dependencies. This repository's
MIT license does not relicense third-party components.
