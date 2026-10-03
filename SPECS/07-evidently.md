# Evidently quality and regression reports

Evidently is the selected local evaluation/reporting library alongside MLflow.
The initial scope is offline reports on versioned pilot cases and assessments;
no Evidently Cloud account or separate monitoring service is required. Package
versions and report formats must be pinned during implementation.

## Evaluation responsibilities

**HR-EVAL-001 — Comparable input.** Evaluation input MUST use the versioned
case IDs, source revisions, question sets, and dataset digests defined by
HR-TRACK-004. Baseline/current comparison MUST identify provider/model, prompt,
policy, abstraction profile, and metric-definition versions. Paired comparisons
require the same cases and source scope. Different corpora MUST be explicitly
labelled and stratified where appropriate, not presented as model improvement.
Missing assessments MUST remain missing and their coverage MUST be reported.

**HR-EVAL-002 — Local reports.** Produce local JSON and HTML reports with
per-case outcomes and aggregates for grammar/reference validity, omissions,
identity corrections, false architecture changes, human correctness, missed
violations, unsupported certainty, review time, and latency where available.
Use applicable Evidently metrics or explicitly defined custom metrics over the
assessment table; do not assume that a built-in metric understands Hypercode
or source-code architecture. Deterministic, human, and LLM-judge assessments
MUST remain distinguishable. Report IDs and source dataset digests MUST be
included in the result metadata.

**HR-EVAL-003 — Regression semantics.** Thresholds and baseline selection MUST
be operator-reviewed and versioned before a comparison is used as a gate.
The first pilot is report-only: a quality dashboard does not authorize or block
individual GitHub publications. Existing eligibility/artifact/publication gates
remain authoritative. Changed distributions of PR size, type, language, or
coverage can signal a changed workload; they MUST NOT by themselves be reported
as evidence of incorrect explanations or model degradation. A 5–10-case pilot
needs per-case results and limitations, not unsupported statistical conclusions.

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
runs, workflow traces, and assessment lineage. Evidently consumes versioned
assessment data and produces report artifacts. Log sanitized report JSON/HTML,
report/dataset digests, baseline/current run IDs, and selected numeric summaries
into the corresponding MLflow evaluation run, subject to the explicit sanitized
report allowance in HR-TRACK-003. Reports containing source-content-bearing
fields MUST NOT use that allowance. This is a planned HyperReview
adapter, not a claimed preinstalled integration. Shared metric definitions MUST
have one versioned source of truth; exporting the same assessment through both
tools MUST NOT count as independent evidence or duplicate evaluation cases.
A report write/upload failure MUST be recorded and recovered without invoking
the analysis model again.

## Official references

Evidently supports configurable reports, test conditions, local exports, and
custom evaluation. HyperReview supplies the domain definitions and policy above.

- [Evidently repository and report examples](https://github.com/evidentlyai/evidently).
- [Evidently documentation](https://docs.evidentlyai.com/introduction).

The upstream Evidently repository is Apache-2.0 licensed; preserve applicable
license/notice obligations when redistributing dependencies. This repository's
MIT license does not relicense third-party components.
