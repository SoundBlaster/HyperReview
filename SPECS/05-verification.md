# Verification and pilot evaluation

These are acceptance scenarios for future implementation, not tests already
performed. Parser acceptance of `.hc`/`.hcs` proves model syntax and property
validation only; it does not prove any worker or security behavior.

| ID | Requirement | Acceptance scenario |
|---|---|---|
| HR-VERIFY-001 | HR-SEC-001 | Own-author, allowlisted, same-repo open PR is eligible; other author, external fork, draft, closed, and non-allowlisted PR are rejected before model invocation. |
| HR-VERIFY-002 | HR-DATA-001, HR-DATA-006 | Push or base advancement invalidates an old job; pre-write changes block publication; a write-time race produces a pinned, explicitly stale comment and a queued refresh. |
| HR-VERIFY-003 | HR-SEC-002, HR-SEC-003 | Adversarial source/AGENTS text requesting execution, secrets, endpoint changes, or publishing cannot invoke tools or alter broker policy; adapter exposes only the evidence pack. |
| HR-VERIFY-004 | HR-DATA-002 | A source rename with preserved responsibility retains architecture identity; ambiguous splits are surfaced rather than manufactured into a confident diff. |
| HR-VERIFY-005 | HR-DATA-003 | Missing references, revision mismatch, unsupported factual assertions, and incomplete scan coverage cannot produce an unqualified observed/compliance claim. |
| HR-VERIFY-006 | HR-DATA-004, HR-DATA-006 | Restart and lost write response recover one marked comment; unchanged jobs are deduplicated; concurrent polls acquire only one lease. |
| HR-VERIFY-007 | HR-ARCH-002, HR-SEC-004 | Backend profiles record exact model and endpoint; cloud fallback is refused; Codex isolation capability failure disables the backend. |
| HR-VERIFY-008 | HR-PROD-002, HR-PROD-006 | Documentation-only and implementation-only refactors may yield identical architecture; no structural change is invented to make output interesting. |
| HR-VERIFY-009 | HR-DATA-004, HR-SEC-007 | Timeout, oversized input, unavailable provider, invalid output, and failed repair end in a recorded non-publishing state. |
| HR-VERIFY-010 | HR-ARCH-004 | Default and each backend/delivery combination validate; contracts remain global; out-of-bound concurrency fails validation in every context. |
| HR-VERIFY-011 | HR-SEC-005, HR-PROD-004 | Preview performs no GitHub writes; publishing without explicit authorization is rejected, even with a true model/config field. |
| HR-VERIFY-012 | HR-SEC-006 | Retention removes expired bundles without credentials in logs or loss of deduplication receipts. |
| HR-VERIFY-013 | HR-TRACK-001, HR-TRACK-002 | One analysis and its repair attempts have correlated MLflow records with pinned versions and workflow-stage timings. |
| HR-VERIFY-014 | HR-TRACK-003, HR-TRACK-005 | Metadata-only tracking excludes source/prompts/response bodies and credentials; scorers cannot trigger an unconfigured remote judge. |
| HR-VERIFY-015 | HR-TRACK-004, HR-TRACK-005 | Versioned pilot cases retain expert expectations and distinguish deterministic, human, and LLM assessments. |
| HR-VERIFY-016 | HR-TRACK-006 | Tracking outage spools bounded events, marks preview pending, blocks publication, and recovers without repeated inference or duplicate logical results. |
| HR-VERIFY-017 | HR-EVAL-001, HR-EVAL-003 | Matched cases produce baseline/current reports; different corpora and missing labels are disclosed rather than interpreted as a quality regression. |
| HR-VERIFY-018 | HR-EVAL-004 | Default Evidently reports and their MLflow exports contain sanitized assessments only; no implicit Cloud/embedding/judge call occurs. |
| HR-VERIFY-019 | HR-EVAL-002, HR-EVAL-005 | JSON/HTML report digests and summaries are correlated to MLflow runs without duplicate cases or conflicting metric definitions; export recovery does not repeat inference. |

## Human evaluation

Before integration with a scheduler, record 5–10 PR cases, their source revisions,
the architectural questions, and expert reference answers. Include at least
one known violation in a controlled fixture and one case with incomplete
coverage. Compare ordinary PR review, free-form LLM explanation, and HyperReview
with matched questions and input scope. Counterbalance the order or use different
reviewers to avoid learning from earlier conditions.

Use [MLflow](06-mlflow.md) to record versioned cases and assessments, and
[Evidently](07-evidently.md) to produce comparable local quality reports.
Record correctness, review time, missed violations, unsupported certainty,
false architectural changes, manual corrections to IDs/projections, model
latency, and ongoing model-maintenance effort. Acceptance needs no reduction in
violation detection or accuracy, useful source traceability, and a demonstrable
benefit in review time or correctness. This small pilot does not establish
population-level superiority; report per-case results and limitations.

Offline fixture checks precede real model runs. Live GitHub publishing and
provider calls are separately enabled integration checks; ordinary verification
must not depend on credentials, network access, or a paid model.
