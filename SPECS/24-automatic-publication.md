# Automatic publication of compiled private previews

An independently configured local publisher consumes the existing private-preview
worker. The operator creates a closed `hyperreview.publication-worker-config.v1`
with explicit `--authorize-repository` flags and `--authorize-mode comment`. This
is standing authority for those repositories. A model, analyzed source, scheduler
tick, or `.hcs` value cannot grant that authority. Manual one-shot publication
retains its exact-plan authorization interface.

## Scope and boundaries

- Only repositories already selected in the pinned private-preview configuration
  and present in the application allowlist can be authorized. The existing
  authenticated-account, author, same-repository, open/non-draft and exact
  base/head/merge-base gates remain mandatory in the publisher broker.
- The source configuration's full SHA256 is pinned. A different source config or
  standing grant requires a new publisher state root; it cannot silently reuse
  another grant's journal. Source generation settings and code fingerprints are
  checked when selecting a completed source job.
- One tick processes at most one preview. It cannot invoke a model, create a
  review thread, approve, merge, push, or edit someone else's comment. It creates
  or updates only the existing operator-owned HyperReview issue-comment marker.
- Publication does not certify the inferred architectural interpretation or
  assert that application tests ran. It preserves the compact preview's scope
  and limitations. MLflow receives only the existing sanitized metadata event.

## Snapshot, tracking and publication

The publisher uses a separate private root, journal, lock and LaunchAgent label
`com.hyperreview.publish`. It acquires the upstream worker lock while validating
the complete 14-file manifest and copying a current completed preview. The
original preview bundle and its upstream manifest remain unchanged.

The delivery key is the upstream preview job identity. Snapshot identities bind
all immutable source/request/result/IR/receipt files and the complete original
tracking event, including correlation ID. Only tracking metadata and rendered
previews can change in the snapshot. Every resume checks those identities;
unknown files, symlinks, nonprivate files and oversized artifacts stop delivery.
Bounded owner-private `.tracking-*` temporary files from interrupted atomic
refreshes are removed before identity/expiry checks.

The existing MLflow outbox confirms metadata delivery before refreshing both
preview renderings and planning publication. No tracking success is fabricated.
The plan must be ready and refer to the authorized repository and PR. Its exact
directory, plan SHA256 and comment SHA256 are committed to the local journal
**before** entering the existing comment broker.

The broker uses the ordinary shared publication-state root by default, including
the same per-PR lock as manual publication. It performs fresh eligibility,
revision and comment-inventory checks, verifies the returned comment, and marks
that comment stale if revisions change during the write.

## Recovery, limits and retention

`tracking → publishing → published` is the ordinary delivery path. After an
uncertain write or a hard interruption, the publisher reuses the **same saved
plan and digests**. The existing broker reconciles exact-body owned markers;
the worker never blindly creates a second comment or replans a pending write.

Tracking/read failures retry within a budget of three delivery executions. A
read-related blocked plan remains retryable, including derived revision blockers
caused by missing reads. A complete observation of stale revisions, ineligibility
or duplicate markers is terminal `blocked`. Exhaustion becomes `needs_attention`;
it does not rerun inference. Post-write stale reconciliation reuses the same plan
within the same budget. Each new revision produces its own upstream job identity.

The queue prioritizes incomplete deliveries, then selects the newest eligible
upstream preview not already journaled. There are at most 2048 delivery receipts;
capacity stops new work. Terminal and orphan snapshot/plan artifacts expire after
seven days while receipts remain. Pending and `needs_attention` delivery artifacts
are retained for explicit reconciliation, including exact plans after retry
exhaustion. Logs rotate at the existing 64-KiB limit. Attempts, fixed failures,
digests and comment IDs are journaled; source and model prose stay in private
artifacts, never the journal or process logs.

The interval is 300–86400 seconds. One shared process lock serializes publisher
ticks; a concurrent tick reports `busy`. Tracking has its existing 120-second
bound, each GitHub read client has a fresh 60-second deadline, and comment writes
retain the broker's 60-second bound. These are component budgets, not a promise
that a complete tick finishes within one polling interval.

## Operation

```text
hyperreview publication-worker-config --preview-config ABS_CONFIG \
  --authorize-repository OWNER/REPO --authorize-mode comment
hyperreview publication-worker-tick --config ABS_PUBLICATION_CONFIG
hyperreview publication-worker-status --config ABS_PUBLICATION_CONFIG
hyperreview publication-worker-launchd-plan --config ABS_PUBLICATION_CONFIG \
  --python ABS_PYTHON
```

The plan generator does not install or start anything. Install the reviewed plist
as `~/Library/LaunchAgents/com.hyperreview.publish.plist`, mode 0600, then enable
and bootstrap `gui/<uid>/com.hyperreview.publish`. Disable/unload that label to
stop scheduled writes; a running remote operation may still require receipt
reconciliation. Private-preview inference remains independently configurable.

`delivery_failed` and `capacity_reached` return CLI exit 1. Status exposes at most
32 recent delivery summaries. No successful publication is claimed without the
existing broker's confirmation. Runtime delivery evidence is distinct from CI
and from semantic assessment of the generated explanation.
