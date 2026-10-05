# Controlled one-shot publication

## Scope

This increment adds an explicitly invoked command that may create or update one
ordinary issue comment for an allowlisted pull request. It does not add polling,
automatic authorization, approvals, merges, pushes, or review-thread actions.

## Contract

**HR-PUBLISH-001 — Reviewed artifact binding.** The operator MUST provide the
SHA256 digests of the exact saved `plan.json` and `comment.md` being reviewed.
The broker MUST reread both bounded regular files, reject symlinks and digest
mismatches, and require a ready dry-run plan with no blockers, confirmed
tracking, an allowlisted repository, and a body bound to the preview digest.

**HR-PUBLISH-002 — Explicit authority.** Each invocation MUST specify the exact
repository and delivery mode `comment`. This flag is an operator action, not a
policy value from `.hc`/`.hcs`. The broker MUST still enforce configured account,
author, same-repository, open/non-draft, allowlist, and revision rules.

**HR-PUBLISH-003 — Serialized fresh gate.** The broker MUST hold a private
per-repository/PR process lock across fresh account, PR, base/head/merge-base,
and complete marked-comment inventory checks and the write. The fresh intended
action and target comment ID MUST still match the reviewed plan. Duplicate owned
markers, incomplete inventory, changed revisions, or changed action MUST stop
before writing.

**HR-PUBLISH-004 — Narrow write.** The only permitted remote mutations are POST
to create or PATCH to update one ordinary issue comment authored by the
authenticated operator and bearing the HyperReview marker. Request bodies MUST
be sent on stdin, not as command-line arguments. All other GitHub mutation
endpoints remain unavailable to the publisher.

**HR-PUBLISH-005 — Recovery and confirmation.** A private redacted per-PR
operation receipt MUST be persisted before a remote write and after confirmed
completion. On a lost response, a complete fresh inventory MUST identify a
unique exact-body owned marker before the broker records success. It MUST NOT
blindly repeat a create. After a write the broker MUST confirm comment ID and
exact body, then recheck PR revisions. If they changed, it MUST mark that same
comment visibly stale and persist a stale/reconciliation state; it MUST NOT
report ordinary success.

**HR-PUBLISH-006 — Idempotent repeat.** A completed receipt with the same exact
plan and comment digests MUST return the existing comment ID without writing
again. Pending operations MUST be reconciled with the live marker inventory;
receipt contents MUST exclude credentials and source text.

## CLI

```text
hyperreview publish \
  --plan-dir ABS \
  --expected-plan-sha256 HEX64 \
  --expected-comment-sha256 HEX64 \
  --authorize-repository OWNER/REPO \
  --authorize-mode comment \
  [--state-root ABS]
```

Exit status is 0 for published or already-published, 2 when a write completed
but the comment was marked stale or needs reconciliation, and 1 when the gate or
operation failed. Errors are sanitized; receipts and locks use a private local
state directory.

## Evidence and remaining stages

Offline tests exercise artifact binding, stale pre-write state, idempotent
receipts, create/update targeting, uncertain create recovery, post-write revision
changes, and mutation boundaries. The per-PR lock is implemented; concurrent
process stress verification remains part of later operational work. These
fixtures do not establish successful GitHub authentication, permissions, or a
real publication. The designated SpecGraph pilot remains a separately approved
step after CI and review. The launchd worker remains a later phase and cannot
grant publication authorization.
