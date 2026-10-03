# MLflow tracking and evaluation

MLflow is the selected experiment/tracing/evaluation system for HyperReview.
This is an implementation requirement, not a running MLflow installation.
The initial deployment is a loopback-only tracking server on the operator's
MacBook. The MLflow package/version and server schema must be pinned when
implementation starts; this specification does not choose an unverified version.

## Run and trace contracts

**HR-TRACK-001 — Analysis identity.** Every analysis MUST be associated with an
MLflow experiment and a run once tracking delivery is confirmed, with
attempt-level records linked to the same job. Before contacting MLflow, assign
and persist a local tracking correlation ID shared by the bundle, operational
receipt, and spooled events. During `tracking_pending`, server-issued IDs MAY
be absent. Recovery MUST reconcile that same correlation ID with the resulting
experiment/run/trace IDs without changing job or attempt identity.
Record job identity, repository/PR, source revisions, evidence digest, exact
provider/model identity when available, prompt and abstraction-profile versions,
Hypercode version, policy/schema versions, and delivery mode. Attempts and
repairs MUST remain distinguishable. MLflow IDs MUST be stored in the operational
job receipt so the local result and experiment record can be correlated.

**HR-TRACK-002 — Manual instrumentation.** Use manually instrumented spans for
collection, inference, projection validation, rendering, and publication.
The operator's workflow trace is different from a trace of analyzed PR behavior;
it MUST NOT become evidence that the analyzed program executed those steps.
Record elapsed times, input/output sizes, attempts, validity, omissions, and
available provider token counts. Missing metrics are unavailable, not zero.
Stage names and span data MUST be controlled by the application. Automatic
provider tracing that captures raw prompts/responses MUST be disabled by default.

**HR-TRACK-003 — Data minimization.** Default tracking MUST contain metadata,
digests, counts, decisions, and sanitized assessments; raw source, full prompts,
model response bodies, and source-content-bearing output artifacts (including
projections, claim text, and Markdown previews) MUST NOT be uploaded by default.
Sanitized Evidently JSON/HTML reports under HR-EVAL-004/005 are permitted when
they contain only allowed assessment metadata and metrics; sanitization MUST
exclude source excerpts, prompts, response bodies, claim text, and credentials
from report data, labels, and embedded content. Sanitization does not authorize
uploading other source-derived artifacts. Keep full analysis bundles in the
separately managed local result store. An optional content-capture mode needs explicit operator authorization
for the selected repository and destination, client-side filtering before
logging, and dedicated retention. Credentials MUST never be logged, even in
content-capture mode. Tracing hooks/redaction are implementation aids, not proof
that every sensitive value is recognized. Local tracking MUST NOT silently
redirect to a remote server. Bind the server to loopback and keep storage out
of analyzed checkouts.

## Evaluation contract

**HR-TRACK-004 — Versioned pilot cases.** Evaluation cases MUST identify pinned
PR revisions or controlled fixtures, question set, expected answers/violations,
input scope, and dataset version/digest. Keep reviewer condition and order in
assessment records. Log deterministic metrics such as grammar validity,
reference validity, coverage omissions, and false/missing structural changes
alongside human accuracy, missed violations, review time, and correction effort.
The metric definition and assessor identity/type MUST be recorded.

**HR-TRACK-005 — Assessment authority.** MLflow GenAI evaluation may use custom
scorers and recorded feedback. Deterministic checks, human judgments, and
LLM-judge scores MUST be labelled separately. No MLflow score establishes
architecture conformance by itself. A judge model requires an explicitly
configured backend and the same source-transmission policy as analysis; a
built-in scorer MUST NOT silently invoke a cloud model. Metadata-only tracking
must use sanitized evaluation records; evaluation over full prompts/traces needs
the optional content-capture authorization. Reusing an existing trace for
scoring MUST NOT count as a fresh independent generation.

Evidently supplies the local quality/reporting layer over these assessments;
see [its handoff contract](07-evidently.md). MLflow tracing and Evidently reports
are complementary views over shared evidence, not independent confirmations.

## Operational boundary

**HR-TRACK-006 — Separate authority.** The operational state store owns queue
leases, deduplication, stale revisions, comment IDs, and write recovery. MLflow
stores experiment/assessment information and MUST NOT authorize publication or
serve as the worker queue. A tracking outage MUST spool sanitized events into a
bounded local queue, report `tracking_pending`, and retry delivery without
re-running inference. If the spool budget is exhausted, stop new analyses with
a recorded tracking failure. Preview may remain available with an explicit
tracking-pending status; publication MUST wait for a tracking receipt in the
initial profile. Resending tracking events MUST preserve attempt identity and
avoid duplicate logical results. Operational receipts survive result-bundle
retention; MLflow run/trace retention is separately documented and managed.

## Official references

These references establish MLflow capabilities; the obligations above are
HyperReview design decisions.

- [Manual tracing](https://mlflow.org/docs/latest/genai/tracing/app-instrumentation/manual-tracing/).
- [Client-side trace filtering](https://mlflow.org/docs/latest/genai/tracing/observe-with-traces/masking/).
- [Trace evaluation and human feedback](https://mlflow.org/docs/latest/genai/eval-monitor/running-evaluation/traces/).
- [Self-hosted tracking server](https://mlflow.org/docs/latest/self-hosting/architecture/tracking-server/).
