# Automatic review-start threads

The optional `hyperreview.worker-config.v3` extends the pinned private-preview
worker with a standing, repository-scoped review-thread grant. V1 remains
intake-only; v2 remains private generation without GitHub mutation authority.
The existing manual gate command keeps its separate exact-plan authorization.

## Operator configuration

V3 contains the v2 keys and a closed `review_gate` object:

- `repositories`: a nonempty, unique subset of the worker's allowlisted repos;
- `eta_seconds`: an integer from 300 through 3600, default 600 in the CLI;
- `state_root`: an absolute private location for gate plans and write receipts.

Creation requires `--authorize-review-gates`, at least one explicit
`--review-gate-repository`, and the existing private-preview/cloud/pin flags.
Neither source content, model output nor `.hcs` values can grant this authority.
The grant participates in analysis job identity. It is independent of standing
ordinary-comment publication authority.

## Before analysis

For an eligible current PR, the worker chooses an added RIGHT-side line in a
supported, nonexcluded changed file. It creates one owned inline review comment
with a durable per-job marker, actual UTC start time and informational ETA.
An unavailable supported anchor stops that job before inference. No source file
or command from the analyzed PR is executed.

The exact creation plan and comment digests are persisted before a possible
remote write. An interrupted or uncertain creation is reconciled from the
complete bounded owned-comment inventory; the worker does not blindly create
another gate. Its GraphQL thread inventory must bind the root comment, author,
repository, PR, head and marker to an unresolved thread before the model starts.

An unresolved conversation participates in merge blocking only where GitHub
rules require review-thread resolution. Administrators and repository policies
remain responsible for actual merge enforcement; HyperReview does not change
rulesets or treat an inline comment as an atomic GitHub lock. ETA expiry does not
release a gate.

The gate transaction uses its own bounded GitHub read client (120 seconds),
separate from a short revision observation (30 seconds). Creation, inventory and
thread binding must not consume an already-exhausted revision-check deadline.

## Completion and recovery

The analysis success condition is a committed `preview_ready` bundle followed
by fresh eligibility and revision checks. It is not a human quality assessment
or approval of the implementation. After success the controller posts its
idempotent completion reply and resolves only its own journaled automatic thread.
Ordinary comment publication is independent and can happen afterward. Its summary
includes the validated permalink back to the review-start thread.

After ordinary publication is confirmed, the publisher adds one short reply in
that completed automatic thread, linking back to the review summary and naming
the reviewed revision. This requires both the publisher repository grant and
the pinned v3 source's thread grant. The exact retained publication plan/body
digests, delivered comment ID, live comment body/author/PR and journaled root are
checked before a possible write. Existing completed deliveries with retained
plans are eligible too, including a PR that has since merged.

The link has its own per-job marker and journal, one possible POST and at most
three recovery passes. An uncertain POST is reconciled by complete bounded
comment inventory; it is never blindly repeated. A changed summary body blocks
a new link for that older delivery. Failures leave ordinary publication marked
successful and never reopen/resolve gates or replay inference. Pending link
plans remain retained. Legacy v1/v2 sources grant no thread notification writes.
Ordinary incomplete deliveries and newly available previews take priority over
old notification backfills, which run only when no ordinary delivery is ready.

Once an analysis is durably `failed` (including an interrupted job), its own
automatic thread receives a distinct `failed_released` reply explaining that
no review or approval was produced and that a tool failure must not block merge.
Only after confirming this reply does the controller resolve the exact journaled
thread. Its terminal gate status is `failed_released`, completion outcome remains
`failed`, and the preview job retains its failure code. No preview is published,
no inference is replayed, and no earlier gates are released by this failure.
A stale analysis keeps its gate open until an eligible replacement review succeeds.
Successful current-revision analysis may release earlier automatic gates for the
same PR after verifying each journaled root and ownership. Manual gates and
other people's discussions are outside this authority.

Thread completion is separate from the model execution journal. A completion
write/read failure cannot change a completed preview into a failed generation
or resend its source. A later due tick reconciles at most one pending gate
completion before selecting more analysis work. Mutation/reconciliation budgets
are bounded; unresolved outcomes remain visible for operator attention with
their exact private plans retained. The controller never infers a successful
remote write from a local exception or a deadline.

Failure release uses the existing ownership, grant, root binding and mutation
limits. Recovery verifies the exact failure-release reply when resolution already
happened remotely. A new reply marker preserves earlier failure notices without
editing their historical wording. Reconciliation can release older committed
failures that previously kept their gates open; it does not repeatedly process
`failed_released` records or relabel them when a later review succeeds. An
unconfirmed notification or resolution stays pending for bounded recovery.

Generation failures retain only a closed diagnostic code: known Codex process,
timeout, event, output or isolation failures, or one/two allowlisted plan issue
codes. Arbitrary provider exception text, raw responses and source excerpts are
not persisted. Unknown exceptions retain the generic failure classification.

The existing source worker's lock serializes gate creation, generation and
completion. Gate records bind the operator policy, analysis job, repository,
PR, revisions, plan/comment hashes, root comment, thread and permalink. Logs and
status expose fixed outcomes and identifiers rather than source or model prose.
Gated-worker `github_writes` is unavailable rather than an incorrect zero after
ambiguous remote operations.

## Commands

Use the native/compiler pin options described in the v2 contract, then add:

```text
worker-config --private-preview --allow-cloud-source ... \
  --authorize-review-gates \
  --review-gate-repository 0al-spec/SpecGraph \
  --review-gate-eta-seconds 600
```

The regular worker tick/status/LaunchAgent-plan commands accept v3. The plan
generator does not install a service. Review the expanded write authority before
replacing a live preview timer's config. A publisher configured with that v3
source config carries the gate permalink into its ordinary review summary.

Operational evidence must distinguish a created unresolved thread, model and
compiler success, verified thread resolution, comment publication and GitHub
ruleset enforcement. A compiled `.hc` diff alone establishes none of the latter.
