# Manual intake milestone

This is the first P1 increment. `python3 -m hyperreview review --preview` collects
evidence; it does not produce the complete analysis bundle required by
HR-DATA-005. Its stage is `evidence_collected`, never `ready` or `completed`.
The local correlation ID is available for future tracking reconciliation;
`tracking_status=not_started` does not imply an MLflow outage or receipt.

## Implemented scope

- Trusted constants select `0al-spec/SpecGraph` and `0al-spec/Hypercode`, author
  and authenticated account `SoundBlaster`, open/non-draft/same-repository PRs.
  Account mismatch fails visibly before source collection (HR-SEC-001).
- Read pinned base/head metadata and compute merge base via GitHub's comparison
  API. Complete non-truncated git trees determine changed paths, avoiding the
  compare API's 300-file inventory cap. Rename hints come from that API; at its
  cap, hints may be incomplete and deletion/addition pairs remain unresolved.
- Read regular blobs at merge-base/head revisions. Verify Git blob SHA-1 and
  record content SHA-256, revision, path, and LF-based line range. Mode `120000`
  symlinks, submodules, unsupported formats, operator files, and sensitive path
  patterns are excluded. Empty files have null line bounds.
- Limit the whole encoded evidence pack to 262144 bytes, select at most 30
  logical changed files (before/after share one slot), cap each API response to
  4 MiB, and impose a 300-second read deadline with 60-second per-call bounds.
  Oversized files are omitted whole, with no silent content truncation. An
  oversized initial inventory fails intake rather than claiming coverage.
- Record at most the first 100 GitHub check runs, their checked head SHA and
  retrieval time. Mismatched revisions, paging limits, and read failures are
  explicit. Commit-status contexts and check output/logs are not collected.
- Recheck eligibility and base/head revisions before saving. Fail on stale
  revisions. Save source only as data, with 0700 bundle directories and 0600
  files; reject symlinks in the operator output path. No checkout, git hooks,
  package installation, source execution, or GitHub mutation is used.

## Evidence boundaries

The pack includes only selected changed files. Surrounding files, PR-authored
descriptions/comments, execution behavior, and accepted architectural intent are
not collected. It includes a complete path inventory within the tree/API limits,
not a claim of complete source analysis or architectural identity mapping.

Path-based credential exclusions cannot prove absence of secrets embedded in
otherwise ordinary source. This increment has no model or tracking destination;
a content-filtering/export boundary must be implemented before passing packs
to either. Raw source and filenames are untrusted data. Intake previews show
inventory and limitations; they do not invent architecture findings.

There is no operational queue, lease, deduplication, retry, automatic retention,
model token budgeting, tracking receipt, or publication gate yet. An API or
schema failure returns a nonzero exit status without a conforming saved pack.
Individual source/check read failures are disclosed omissions when collection
can still finish. The initial manual smoke case is SpecGraph PR #761; subsequent
runs must pin their own revisions and remain eligible at collection time.

## Exit evidence and next increment

Offline fixtures cover eligibility, path exclusions, revision changes, blob
integrity, symlinks, bytes, source/check provenance, and private output. Hosted
CI runs fixtures with no credentials; a live intake run only establishes the
API read and local artifact path for its recorded revisions.

Next, define a provider-neutral request/result schema and implement the
credential-free model input boundary with explicit content filtering. Then
select and verify a local HTTP backend before producing paired `.hc` projections.
