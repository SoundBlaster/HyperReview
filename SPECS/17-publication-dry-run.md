# Read-only publication dry-run

## Implemented subset of P3

`publish-plan` prepares a private draft and a gate receipt for one validated
compact preview. It performs GitHub reads and local writes only. It does not
publish, authorize publication, mark a job completed, or act as a worker.

**HR-PLAN-001.** Require an explicit SHA256 of the compact preview reviewed by
the operator. Validate the evidence/request/result/compiler chain and the exact
current compact rendering. Reject changed or invalid local artifacts. Require a
confirmed MLflow receipt bound to the same metadata event. User feedback remains
separate and is not an authorization or quality threshold.
This validates an operator-controlled local receipt, not a fresh SDK audit or
signed attestation of server state.

**HR-PLAN-002.** Apply trusted intake policy to the authenticated account and
live PR: exact allowlist, configured author, same-repository head, open and
non-draft. Compare live base/head and computed merge-base with the pinned
evidence. Recheck state after comment inventory to detect intervening changes.
Known stale or ineligible previews produce a blocked local plan.

**HR-PLAN-003.** Inspect ordinary issue comments using bounded pagination. Only
an operator-owned comment with the fixed `<!-- hyperreview:comment:v1 -->` marker
may be selected. Duplicate owned markers or incomplete inventory block planning.
The action is `create`, `update`, or `unchanged`; blocked plans have no executable
action. Bound the comment draft to 65536 UTF-8 bytes.

**HR-PLAN-004.** Save `plan.json` and `comment.md` in a fresh private directory
under the trusted output root, outside the original preview. Record pinned and
current revisions, result/preview identities, tracking IDs, gate outcomes and
check time. Exclude feedback notes, credentials and source bodies from the plan.
The draft retains the preview's inferred status, limitations and pinned links.

## CLI and boundaries

`publish-plan --bundle ABS --expected-preview-sha256 HEX64` returns 0 for a ready
snapshot, 2 for a blocked snapshot, and 1 when no valid plan could be saved.
No GitHub write endpoint or publish flag exists in this increment.

A ready snapshot can become stale immediately after the last read. It does not
prove behavioral correctness, current CI success, or enduring eligibility.
The subsequent writer still needs explicit repository/mode authorization,
serialization, fresh pre-write checks, comment ownership checks, deduplication,
post-write race detection and uncertain-response recovery under HR-DATA-006 and
HR-SEC-005. None of those write behaviors are claimed by this milestone.

## Verification

Offline fixtures cover create/update/unchanged, eligibility, stale base/head and
merge-base, a change during planning, tracking and compact-preview binding,
foreign/duplicate markers, bounded pagination, private output and nonmutation.
A historical-only evidence pack is rejected before publication planning makes
any GitHub API calls. The historical intake path is a separate exploratory
workflow: it records the merged revision, carries `historical_read_only` through
the evidence digest and prepared request, and sets `publication_allowed` to
false. It cannot satisfy P3.4 live publication evidence.
