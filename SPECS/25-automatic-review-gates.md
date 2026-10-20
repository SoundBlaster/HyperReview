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

Failed and interrupted analyses keep their threads open with an explicit failure
notice; they are not silently retried or reported as successful reviews. A stale
analysis keeps its gate open until an eligible replacement review succeeds.
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
