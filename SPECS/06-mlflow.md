# MLflow tracking and evaluation

MLflow is the selected experiment/tracing/evaluation system for HyperReview.
The initial implementation pins MLflow `3.16.1` and uses a direct local SQLite
SDK connection with a loopback-only UI server on the operator's MacBook.
[The implemented subset](12-local-tracking.md) records its delivery and recovery
limits; the full tracing, evaluation and worker obligations below remain the
target contract where they exceed that subset.

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

**HR-TRACK-004 — Preview feedback and technical evaluation.** The P2 product
feedback is one user's assessment of a preview for their own PR: `ok` or
`not_ok`, with an optional note. Every feedback record MUST identify the exact
PR base/head revisions and projection version shown. The verdict and revision
lineage MAY be associated with the MLflow preview record; free-text notes MUST
remain in the local result store by default and MUST NOT enter the default
metadata-only MLflow payload. The local `feedback` CLI implements capture
([contract](16-preview-feedback.md)); associating its verdict with an MLflow run
is not implemented and records remain local. Separately, deterministic compiler, source-ID,
provenance, and technical-quality fixtures MUST retain their version and
assessment type. Their metrics include grammar/reference validity, missing
coverage, and structural changes; they are engineering evidence, not user
feedback or a comparative quality study.

**HR-TRACK-005 — Assessment authority.** MLflow GenAI evaluation may use custom
scorers and recorded feedback. Deterministic checks, human judgments, and
LLM-judge scores MUST be labelled separately. No MLflow score establishes
architecture conformance by itself; an `ok` feedback verdict also does not
establish conformance. Comparative accuracy or review-time studies are optional
research, not a product or publication gate. A judge model requires an explicitly
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
