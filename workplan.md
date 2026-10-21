# HyperReview implementation workplan

## Active direction — stack-independent architecture understanding

The reviewer must understand architecture and documentation across languages,
platforms, frameworks and repositories. Existing Hypercode is a preferred
architecture input when present; it is optional, revision-bound authored evidence.
The governing contract is [stack-independent review](SPECS/26-stack-independent-review.md).

Next delivery follows G1 → G2 → G3:

1. **G1 (PR #42):** composition-plan v3 and
   profile v5 use common relationships, preserve frozen legacy relation semantics
   and require an explanation for an empty relationship result. CI/review and
   integration remain the delivery gates for this branch.
2. **G2 (implemented in this increment):** select architecture, specifications,
   decision records, manifests and bounded unchanged context with common rules.
   Render property changes in `.hcs` and keep operational instructions out of
   public prose. [Contract](SPECS/27-bounded-architecture-context.md).
3. **G3:** replay pinned examples through that same core profile and inspect the
   result with ordinary `ok`/`not_ok` feedback. Language-specific navigation is
   optional and can follow demonstrated need.

Repository access, own-PR eligibility, source filtering, budgets and publication
checks remain trusted operational policy. Current service grants are unchanged.
The older phase snapshots below document delivery history, not new exit gates.

### G3 follow-up — source-established names

G1 and G2 landed through #41–43. Fresh common-profile replays of Hunter #22 and
BuildHunter #97 produced compiled `.hc`/`.hcs` sketches and published compact
comments. Human `ok`/`not_ok` assessment and a no-Hypercode example remain open.
The Hunter replay unnecessarily renamed an authored root. Profile v9 / prompt
v15 now asks for exact represented role names, with explicit reasons for real
renames, inferred rescoping or necessary wrappers, and preserves authored owners
and persisting caller roles when showing delegation. Reuse saved evidence for the
follow-up and keep earlier model outputs immutable; no new blocking name gate.

### G3 follow-up — supported relationships

A private v9 replay preserved the authored roles/owners but still inferred a
portable path's dependency on an optional backend without a supporting declared
edge or inspected integration. Profile v10 / prompt v16 requires evidence for
each edge's direction and kind, preserves conditions on genuine optional
dependencies, and distinguishes an actual shared data contract from a capability
label. Unsupported edges are omitted with a specific knowledge gap. Replay the
same immutable Hunter/BuildHunter evidence with Luna 6 Medium; keep prior outputs
and public comments intact. These instructions add no semantic validation gate.


## Review clarity follow-up — SpecGraph #773

Author feedback on [the published sketch](https://github.com/0al-spec/SpecGraph/pull/773#issuecomment-6272175746)
at `6bddebd00e159ba222173c6003671a2d3c24b8db` identifies three concrete gaps:

1. Supply bounded changed workflow/spec/passport/binding excerpts under an
   explicit path policy. General YAML/JSON and operator files remain excluded.
2. Keep the responsibility tree compact; put up to six source-bound relationships
   on existing owners in companion `.hcs`, resolve them into IR, and render a
   table explaining obligations, policy callsites/reuse and build/deploy transfer.
3. Describe omissions precisely. The selected Python contained `run_tests`;
   the unsupported Makefile was the missing orchestration entry point.

The implementation updates the trusted review profile and generation identity;
existing generated bundles remain historical artifacts, never silently rewritten.
Delivered through PRs #38 and #39, with the #773 comment updated through the
existing publication gate. The Hunter follow-up now informs the common G1–G3
direction above. No new repository blocking checks.

---

**Earlier delivery snapshot:** specifications, a parsable desired-system Hypercode model,
and a manual Python pipeline through filtered requests, Codex inference,
and compiled paired projections with local Markdown output and metadata-only
MLflow delivery. Six controlled pilot cases and local Evidently reports are
implemented, with explicit sanitized report export to local MLflow. Local feedback,
read-only publication planning, and a one-shot publisher implementation are
present. The controlled one-shot publisher and recovery path are merged in PR
#20; conditional Hypercode selectors are merged in PR #21. The explicitly
authorized live publication pilot remains the P3 exit gate.
An intake-only P4 increment now adds bounded discovery, private durable request
handoff and a generated launchd plan; it has no model or publication authority.

| Phase | Work | Exit evidence |
|---|---|---|
| P0 — Specification | Agree scope, IDs, data contracts, and provider/delivery profiles | Specification PR; validated `.hc`/`.hcs`; decisions on initial language and model |
| P1 — Manual preview | Implement PR eligibility, pinned evidence collection, paired projection, artifact validation, Markdown output, and local MLflow tracking | One real SpecGraph PR explained locally; acceptance fixtures for evidence, identity, and trust boundaries |
| P2 — Own-PR feedback | Let a user mark a preview for their own PR `ok` or `not_ok`, with an optional note | Feedback is associated with the exact PR revisions and projection version; technical fixtures and reports remain separate |
| P3 — Controlled publishing | Implement the authorized one-shot publisher in gated increments; do not couple it to polling | Local gates and recovery pass; separately authorized test PR receives one correct comment |
| P4 — Local worker | Run only the proven one-shot path under `launchd` | Serialized polling, wake/restart recovery, resource bounds, logs and retention verified |

MLflow `3.16.1` is installed in an isolated optional runtime; its local SQLite
delivery and loopback UI have been exercised. The local Evidently reporting
subset uses a separate optional Python 3.12+ runtime. Intake uses Python 3.10+
standard library, the pinned SpecificationCore policy package and `gh`.
SpecGraph PR #761 is the first intake smoke case. Its selected slice was analyzed
with the existing local LM Studio gpt-oss-20b model, explicit API alias and context
16384. The alias fingerprint is recorded; a weights revision remains unavailable.
Unattended Codex isolation and controlled publishing remain open. Comparative accuracy or
review-time studies are optional research, not release or publication gates.
Executable presence alone does not choose a backend.

## P1 increments

1. Evidence intake: implemented; [scope and limitations](SPECS/08-intake-milestone.md).
2. Provider-neutral request/result schema and a content-filtered model input
   boundary: [contract](SPECS/09-model-contract.md). LM Studio/Ollama transport:
   [local inference](SPECS/10-local-inference.md), with offline fixtures and a
   controlled local readiness probe.
3. Paired Hypercode compilation, identity/provenance validation, and explanation:
   [compiled preview](SPECS/11-compiled-preview.md).
4. Local MLflow tracking and bounded recovery:
   [delivery profile](SPECS/12-local-tracking.md), exercised on the compiled real slice.
   Structured generation now converts one model declaration per identity to paired
   Hypercode and emits a compact Russian preview alongside diagnostic receipts:
   [composition plan](SPECS/15-structured-composition.md). A historical four-file
   PR #761 slice passed ordinary local generation and the real compiler without
   a manual rewrite; semantic usefulness is still for the user to assess.
5. Controlled versioned cases and sanitized local Evidently reports:
   [pilot subset](SPECS/13-pilot-boundaries.md) and [local evaluation handoff](SPECS/14-evaluation-handoff.md).
6. Local own-PR `ok`/`not_ok` feedback with optional notes and exact
   revision/projection/preview fingerprints:
   [feedback record](SPECS/16-preview-feedback.md). This captures usefulness,
   without quality thresholds or publication authority.
7. Read-only publication planning with exact preview binding, confirmed tracking,
   current PR eligibility/revisions and marked-comment inventory:
   [dry-run](SPECS/17-publication-dry-run.md).
   The dry-run is complete. Controlled publishing is the next implementation
   phase; it must remain a separate, explicitly invoked path.
## P3 implementation increments

1. One-shot publication with reviewed artifact digests, explicit repository/mode
   authorization, per-PR serialization, narrow comment writes, recovery receipts
   and stale-after-write handling: [contract](SPECS/20-controlled-publication.md).

## P3 — Controlled publishing stages

1. **P3.1 — One-shot broker gate and write (implemented locally).** Add an explicit `publish` command
   that binds the exact saved plan and comment to operator-reviewed digests and
   an exact repository/mode authorization. Re-read the artifacts, require a
   ready plan and confirmed tracking, then recheck authenticated account, PR
   eligibility, base/head/merge-base, and marked-comment inventory immediately
   before writing. Serialize writers per repository/PR. The command may create
   or update only the single HyperReview-owned marked comment; it never approves,
   merges, pushes, or resolves review threads.
2. **P3.2 — Idempotency and uncertain-response recovery (implemented locally).** Persist a small
   redacted operation receipt before/after the remote write. On timeout or
   restart, find the unique marker and reconcile its comment ID and body before
   retrying; never blindly append a second comment. Reject duplicate owned
   markers and preserve a recoverable pending state.
3. **P3.3 — Post-write race handling (implemented locally).** Recheck PR eligibility and revisions
   after the write. If revisions moved, mark that same comment stale and record
   a refresh-needed receipt; never claim it is current. Confirm exact body/ID
   for create and update paths.
4. **P3.4 — Authorized pilot.** After P3.1–P3.3 and CI pass, select an open,
   non-draft, allowlisted SpecGraph PR by the configured author. Review its
   exact compact preview and saved publication plan, then obtain explicit
   authorization bound to that plan's digests before the one-shot write. Verify
   one comment, safe update/retry, stale revision, tracking gate, and zero
   unintended GitHub writes. A historical or closed PR is suitable for preview
   exploration but cannot satisfy the live-publication exit evidence.

## P4 — Local worker stages

The first [intake-only increment](SPECS/22-worker-intake.md) implements a private
serialized queue, bounded collection retries, request handoff and a generated
LaunchAgent plan. It does not enable unattended inference or publication. Its
provisional intake identity is separate from the full analysis job identity.
The plan is prepared for operator review, not installed by the generator.

1. Wrap the proven one-shot pipeline in a `launchd` job with one active lease
   per PR, a bounded queue, explicit allowlist, and no automatic provider
   fallback.
2. Verify sleep/wake and restart recovery, bounded retries/timeouts, resource
   limits, and sanitized log/receipt retention.
3. Enable unattended operation only after the operator reviews the launch
   configuration and the P3 pilot evidence. Scheduler execution cannot grant
   publication authorization by itself.

**Current step:** P3.1–P3.3 are complete and merged in PR #20; its CI passed.
PR #21 subsequently added conditional selectors. The allowlist now also includes
SessionMonitor; its PR #117 has received an explicitly authorized explanatory
comment and revision-bound updates. This establishes real create/update delivery,
not all P3.4 race/recovery acceptance scenarios. Do not create a dummy PR or
publish to a closed historical PR to bypass eligibility. Further publication
continues to require a fresh compiled/tracked preview and per-plan authorization.
The first P4 intake-only increment is independently read-only; full unattended
inference and publication remain gated on the outstanding pilot and Codex
operational isolation evidence. See [the intake-stage boundary](SPECS/22-worker-intake.md).

A later optional phase may compare explicit SpecGraph architectural intent
against source-derived evidence. It must preserve accepted intent and inferred
projections as separate artifacts and cannot assume graph-shape equality.

Current inference increment: composition-v4 paired-side instructions and one
bounded validation regeneration, with fixed diagnostic codes and per-attempt
metadata. This does not add a durable failed-job journal or unattended worker.

Explanation increment: composition-v6 domain responsibility explanations,
with explicit separation of code changes and comment descriptions. Evaluate
the actual local-model output; structural validity alone is insufficient.
The local gpt-oss-20b pilot still produces generic nodes after regeneration.
This failure prompted the selected Codex pilot below; passing fixture/transport
tests alone does not establish explanation quality.

Selected pilot path: direct Codex CLI generation, `gpt-6-luna` with reasoning
`low`, after a successful isolated probe on PR #769's selected source pair.
The common compilation/tracking pipeline is retained; generic model adapters
are deferred. [Invocation contract](SPECS/18-codex-generation.md).
The integrated default path generated a locally valid plan in one attempt on
the same PR #769 source pair, correctly distinguishing a comment change from
unchanged comparison code and marking external catalog behavior unavailable.
The paired Hypercode projections passed the real compiler and metadata-only
MLflow delivery was confirmed. This is one observed slice, not a general model
quality claim. PR #769 is now closed, so its historical bundle cannot be used
for live publication. Reuse it only for offline review or diagnostics; the P3.4
pilot requires fresh evidence from an eligible open PR.

Project quality integration: one behavior-preserving PR metadata eligibility
Specification backed by SpycificationCore; pinned SpecificationMetrics collection
of application S/U and Python LOC/CC/Cog. CI and local SQLite snapshots retain
scope/status rather than introducing a composite score or quality threshold.
See [contract](SPECS/19-specification-quality.md).


### P4 process isolation increment

An explicit `--isolate-process` generation route wraps the native Codex process
in macOS Seatbelt and a supervised OpenAI-only CONNECT proxy. Native canaries
check permitted workspace/proxy access and denied external reads/writes,
symlink traversal, policy/login mutation, other network/Unix endpoints and
process creation. The macOS CI job repeats these credential-free checks.
Operational evidence for the installed CLI is recorded separately from fixtures.
The live launchd job remains intake-only. Next: after this increment is reviewed,
wire isolated generation into one bounded worker job ending in a private preview;
publication keeps its existing authorization and revision checks.


### P4 bounded private-preview worker

The v2 worker consumes one prepared request through pinned, isolated Codex,
compiler validation and private Markdown. Its separate job journal prevents
automatic replay after ambiguous failure or interruption; eligibility/revisions
are checked before and after work. Intake-only v1 remains supported. The optional
LaunchAgent plan uses a separate label/state root and does not install itself.

The isolation → private-preview stack is merged and its reviewed timer is active.
Real due ticks produced SessionMonitor #117 and SpecGraph #773 private previews.
Comment publication is the separately authorized increment below; automated
review-thread gates remain a later step.

### P4 automatic comment delivery

The isolation/private-preview stack (#30 → #31) is merged. The Mac's isolated
preview timer produced real SessionMonitor #117 and SpecGraph #773 previews.
The operator subsequently requested automatic publication for the selected
repositories. The separate publisher in `publication_worker.py` consumes those
previews under an explicit standing repository grant, confirms local metadata
tracking and invokes the existing fresh-revision comment broker. It reuses exact
pending plans after uncertain writes and preserves the original preview manifest.

The first delivery published the #773 architectural preview in one attempt as
[comment 6272175746](https://github.com/0al-spec/SpecGraph/pull/773#issuecomment-6272175746).
The permanent service remains an operational activation step after integration.
This increment does not automate review-thread gates or merging. PR #33 is now
merged; the permanent publisher confirmed #773 creation and #117 update without
duplicate owned markers.

### P4 automatic review-start gates

The operator requested automatic start threads after enabling publication.
V3 worker configuration grants thread authority for an explicit repository
subset. Analysis starts only after an owned unresolved thread is confirmed;
completed current-revision analysis resolves it. Failure keeps the gate open,
and completion recovery cannot rerun inference. The ordinary review summary
links to that thread. GitHub effective rules for both selected repositories
require review-thread resolution; HyperReview does not change those rules.

Next: integrate and activate the explicit v3 timer config, then observe a real
start → analysis → completion cycle. Automatic PR merging is outside this stage.

## Queue latency follow-up

SpecGraph #784 exposed an unintended five-minute wait between every queue phase.
The persisted discovery time now gates PR-list polling only. Generated agents
wake every 30 seconds; `worker-run` can collect once then immediately process one
preview. Publisher first delivery follows ready local output without waiting for
the retry/reconciliation interval. Intake/publisher retry delays, one-generation
limits, fresh revision checks, standing grants and no-replay journals remain.
Installed services require a separate reviewed update; no journal reset or grant
change is part of this correction.
