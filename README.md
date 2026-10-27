# HyperReview

A local PR reviewer that explains architectural changes using illustrative
Hypercode projections, source references, and explicit evidence boundaries.

**Status: compiled previews with optional local worker publication.** A Python CLI collects pinned PR evidence,
prepares a filtered request, proposes a result through Codex CLI or an explicitly
selected local HTTP provider,
and validates paired projections before rendering a local explanation.
Metadata-only MLflow delivery and recovery are implemented. Controlled pilot
fixtures, local Evidently reports, and explicit sanitized evaluation export to
MLflow are available. Local own-PR feedback capture, a read-only publication dry-run,
and the one-shot publisher implementation are available. Manual publication uses
an exact operator-authorized plan. An explicitly configured private-preview worker
runs pinned isolated Codex; a separate publication worker can deliver its results
under a standing repository-scoped operator grant. Each service has its own
reviewable launchd plan and state. Neither plan generator installs a service.
The Hypercode model still describes the proposed full reviewer.

## The pilot

For an eligible PR, collect pinned before/after source data, build a paired
architecture projection with stable IDs, validate the artifacts, and produce
one concise Markdown explanation with a Hypercode diff. Initial operation is
local preview. The one-shot publisher requires explicit authorization,
eligibility, artifact, tracking-confirmation, and security gates.

The explanation can also show up to six source-bound relationships separately
from the Hypercode containment tree: obligations, policy callsites/reuse, typed
facts, and build/deploy artifact transfer. A narrow configuration path policy
supplies bounded workflow/spec/passport excerpts, with omissions disclosed.
These remain interpretations of declarations and source, not runtime observations.

The repository allowlist is `0al-spec/SpecGraph`, `0al-spec/Hypercode`, and
`SoundBlaster/SessionMonitor`, `SoundBlaster/Hunter`, and `SoundBlaster/BuildHunter`,
with PR author `SoundBlaster` and same-repository heads.
These are operator-owned settings, never instructions loaded from a PR.

## Specifications and architecture

- [Specification index](SPECS/README.md): requirements and acceptance criteria.
- [Product scope](SPECS/01-product.md).
- [Architecture and responsibilities](SPECS/02-architecture.md).
- [Data and lifecycle contracts](SPECS/03-contracts.md).
- [Trust and publication policy](SPECS/04-security.md).
- [Verification and pilot evaluation](SPECS/05-verification.md).
- [MLflow tracking and evaluation](SPECS/06-mlflow.md).
- [Evidently quality and regression reports](SPECS/07-evidently.md).
- [Hypercode model](architecture/README.md): readable `.hc` structure and
  context-resolved `.hcs` configuration.
- [Implementation workplan](workplan.md).

## Design principles

An illustrative projection is an interpretation of source evidence, not an
accepted architecture specification or proof of behavior. Hypercode is used for
composition, context resolution, provenance, and IR comparison. Scanning code,
interpreting responsibilities, checking evidence, and publishing belong to
HyperReview. Canonical expected architecture, when supplied, stays separate
from inferred projections.

MLflow is the selected system for experiment runs, manually instrumented traces,
and pilot evaluation. The first local deployment pins MLflow `3.16.1`, uses
SQLite directly for SDK writes, and serves a loopback-only UI.
Evidently produces local quality/regression reports from versioned assessments;
sanitized report artifacts and summaries are linked to MLflow evaluation runs.
Operational job/publication state remains in a separate store.

Model backends are interchangeable: Codex CLI, LM Studio HTTP API, and Ollama
HTTP API. Backend readiness and isolation must be verified before use; an
installed executable alone does not establish a safe unattended setup.

## Manual evidence preview

For periodic intake, see [local worker intake](SPECS/22-worker-intake.md).
`worker-config`, `worker-tick`, `worker-run`, `worker-status` and `worker-launchd-plan` prepare
the trusted configuration, private queue, requests and reviewable LaunchAgent.
The generator does not install a service. Automatic inference and publishing
remain disabled at this stage.

An input containing only permanently excluded or over-budget source records is
recorded as `skipped`, with fixed omission reasons in `worker-status`, rather
than retried as a generic collection failure. A skip is not a completed review.
Read/identity/unknown omissions keep the bounded failure/retry path.

Requirements: Python 3.10+ and an authenticated `gh` CLI for `github.com`.
Install into a Python 3.10+ environment before running from this repository:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

The runtime uses the commit-pinned `specification-core` package from
[SpycificationCore](https://github.com/SoundBlaster/SpycificationCore) for named
eligibility policy. Optional tracking and measurement dependencies stay separate.

```sh
python3 -m hyperreview review --repo 0al-spec/SpecGraph --pr 761 --preview
```

Choose a currently open, non-draft PR by `SoundBlaster` in the configured
allowlist. The command rejects a different authenticated account or a fork.
It performs GitHub reads and local writes only. `--preview` is required;
publishing is not implemented. PR #761 is the first intake case, not a permanent
fixture: it becomes ineligible when closed or marked as a draft.

Outputs are `evidence.json` and `preview.md` in a fresh private directory under
`~/.local/share/hyperreview/evidence/`. Override the trusted destination using
`--output-root /absolute/operator/path`. Output paths must not traverse symlinks.
Source is read as blobs without checkout or executing repository code. Revisions
are rechecked before saving; a change aborts intake. The preview is pinned to
the collected revisions and can become stale after the final check.

For an already merged PR, use the separate historical-only intake:

```sh
python3 -m hyperreview review-historical --repo 0al-spec/SpecGraph --pr 764 --preview
```

This accepts only merged, non-draft, same-repository PRs by the configured
author. It records the merge identity and marks the evidence and every prepared
request `historical_read_only`; publication is disabled and `publish-plan`
rejects the evidence before making GitHub API calls. The command performs GitHub
reads and private local writes only. It is for exploratory analysis, not the
P3.4 live publication pilot.

The pack is bounded to 262144 encoded JSON bytes and 30 logical changed files
(up to two revisions per file). It records exclusions, read failures, and check
coverage. Source-path filtering is a conservative heuristic, not a guarantee
that arbitrary source text contains no secrets. Full local evidence is not yet
approved input for a model or tracking export. No automatic retention or job
deduplication is implemented; manually remove intake directories when no longer
needed. See [the intake milestone contract](SPECS/08-intake-milestone.md).

Run the offline intake checks:

```sh
python3 -m pip install '.[test]'
python3 -m unittest discover -s tests -v
```

[Intake CI](.github/workflows/intake-validation.yml) runs these fixtures without
GitHub credentials, real PR reads, or model calls.

The Codex output grammar couples each node's type, parent and source references:
an absent side has a null type/parent and no references, while a present side
requires references from that side. Added, removed and retained responsibilities
keep the same flat plan format. Offline schema tests use the pinned test extra;
the runtime converter still checks the complete tree and provenance.

## Prepare a model request

```sh
python3 -m hyperreview prepare --evidence /absolute/path/evidence.json \
  --include-path tools/subject_human_approval_spec.py --max-source-bytes 4096
```

This verifies pack/source digests and pinned provenance, filters known sensitive
forms, and selects whole source records within the trusted slice/byte budget.
It writes a private `request.json` under `~/.local/share/hyperreview/requests/`
without inference or tracking calls. Omissions and unavailable context are
explicit. Filtering uses heuristics; it does not guarantee absence of all secrets.

The [provider-neutral contract](SPECS/09-model-contract.md) binds proposed results
to the request digest, checks identities/references, and keeps model claims
`inferred`. Result-shape validation is separate from Hypercode parsing and
source interpretation quality.

## Generate with Codex

For an outer macOS filesystem/process/egress boundary, add `--isolate-process`:

```sh
python3 -m hyperreview generate --request /absolute/path/request.json \
  --allow-cloud-source --isolate-process
```

This requires a native installed Codex CLI and owner-private file-based login;
unsupported environments stop without falling back. The login is read-only,
so refresh it outside the boundary when needed. The launchd intake job does not
start inference automatically. See [isolation details](SPECS/18-codex-generation.md#outer-process-isolation-on-macos).


The pilot defaults to the installed Codex CLI, `gpt-6-luna`, reasoning `low`,
using the operator's existing Codex authentication. Each invocation requires
`--allow-cloud-source` to acknowledge sending filtered source to the cloud:

```sh
python3 -m hyperreview generate --request /absolute/path/request.json --allow-cloud-source
```

Use `--model`, `--reasoning-effort`, `--codex-executable` and
`--timeout-seconds` for explicit operator settings. Codex inference sends the
filtered source to the configured Codex service; it is not an on-device model.
The runner uses a private temporary directory, ignores user/project instruction
configuration, disables tools/integrations, and audits JSONL events. Process
output, input bytes and total time are bounded. Local HTTP context/output-token
flags are rejected for Codex; those limits are managed by Codex rather than
claimed as locally enforced. See [the Codex invocation contract](SPECS/18-codex-generation.md).

## Explicit local HTTP inference

Load a local model with an appropriate context using the provider's own tools,
then select that exact API model ID:

```sh
python3 -m hyperreview generate --request /absolute/path/request.json \
  --provider lmstudio --model hyperreview-gpt-oss-20b --context-tokens 32768
```

LM Studio defaults to `http://127.0.0.1:1234/v1`; Ollama defaults to
`http://127.0.0.1:11434/api`. An explicit `--endpoint` must use a literal loopback
IP with the provider's exact API path. There are no redirects, proxy routing,
tools, remote fallback, or automatic model downloads. The invocation has bounded
context, response bytes, and time; `--max-tokens` and `--timeout-seconds` are
trusted operator limits. The configured context must not exceed the loaded one.
The HTTP default is 32768 for reviewer profile v4, leaving room for the versioned reviewer profile and
a bounded repair. Load a model with at least that context
or supply an explicit smaller budget; preflight still rejects oversized attempts.

Prompt `composition-v8` combines the shared trusted reviewer profile with provider instructions and asks the provider for structured
`hyperreview.composition-plan.v2` nodes. HyperReview validates the plan and
deterministically converts it to the provider-neutral `hyperreview.result.v2`;
the provider does not author `.hc` or identity-map strings directly.
Node addresses pair a responsibility role with an internal ID; the adapter
renders `.hc` selectors only when the pinned revision has `.hcs` and that role
repeats in the projection.
The prompt and schema guide domain responsibility names and explain what changed
or remained in the selected code. Comment descriptions are kept separate from
behavior evidence; these instructions are not a semantic correctness check. Private
bundles under `~/.local/share/hyperreview/generated/` retain the original plan
as `composition-plan.json`, the canonical result as `result.json`, the request,
and a sanitized `receipt.json`. The stage is `model_generated`, not a completed
review: the derived `.hc` still requires compiler validation and the
interpretation still requires review. No MLflow or GitHub publication occurs.
The packaged `hyperreview/reviewer_profile.md` is shared by Codex, LM Studio,
and Ollama. Its version and SHA-256 are pinned in each prepared request and
generation receipt so previews can be traced to the exact guidance used.
For gpt-oss on LM Studio, use `--instruction-role developer` explicitly; the
role is retained in the receipt. A locally invalid composition plan gets one
bounded repair with a safe error code and field address; Codex receives the
rejected candidate as untrusted data. Transport and envelope failures are
terminal. Both attempts share the timeout. The worker retains up to two exact
candidates and their pinned inputs in separate private diagnostic bundles for
seven days, including on failure. `worker-status` exposes their paths; raw
candidates are excluded from publication and ordinary MLflow exports. See the
[repair controls](evaluations/review-corpus-repair-v1.json).
Prepare a fresh request after a prompt-version change. The four-file smoke selection was run with a
loaded context of 32768 and an output limit of 3072; the conservative byte-budget
preflight can require more context than the source text's tokenizer count.

See [the local inference contract](SPECS/10-local-inference.md) and
[structured composition](SPECS/15-structured-composition.md).

## Compile a paired preview

Supply a trusted absolute compiler path and the SHA256 of that executable:

```sh
python3 -m hyperreview compile --evidence /absolute/path/evidence.json \
  --request /absolute/path/request.json --result /absolute/path/result.json \
  --generation-receipt /absolute/path/receipt.json \
  --compiler /absolute/path/hypercode --compiler-sha256 VERIFIED_BINARY_SHA256
```

The compiler is an external trusted dependency. CI builds reference revision
`7d23efdc9976226a21e1fc301730940d62097607`; the executable fingerprint alone
does not prove source/build provenance. Parse, validation, emitted IR, semantic
diff, and identity/source-side checks must all pass. Failed proposals produce
no validated preview. Each compiled node must have an explicit ID and source
references on its side; a genuinely empty side is a newline-only `.hc` string.

Private bundles under `~/.local/share/hyperreview/previews/` contain evidence,
paired projections and IR, semantic diff, claims (if supplied), receipts, and two
Markdown views. `preview.md` is the verbose diagnostic explanation;
`preview-compact.md` is a concise Russian diff with reasons and revision-specific
source links. Both remain inferred review aids. The stage is
`projections_validated`; tracking has not been confirmed and publication remains
unavailable. See [the compiled-preview contract](SPECS/11-compiled-preview.md).

## Deliver local tracking metadata

The core CLI uses the standard library and SpecificationCore; tracking runs in a separate
optional environment. Install and run the UI outside analyzed checkouts:

```sh
python3 -m venv ~/.local/share/hyperreview/runtime
~/.local/share/hyperreview/runtime/bin/python -m pip install -r requirements-tracking.txt
mkdir -p ~/.local/share/hyperreview/mlflow/artifacts
~/.local/share/hyperreview/runtime/bin/mlflow server --host 127.0.0.1 --port 5050 \
  --workers 1 \
  --backend-store-uri "sqlite:///$HOME/.local/share/hyperreview/mlflow/tracking.db" \
  --artifacts-destination "$HOME/.local/share/hyperreview/mlflow/artifacts" \
  --allowed-hosts '127.0.0.1:5050,localhost:5050' \
  --cors-allowed-origins 'http://127.0.0.1:5050' --x-frame-options DENY
```

The setup paths are trusted operator configuration. Run delivery separately:

```sh
python3 -m hyperreview track --bundle /absolute/path/compiled-preview-bundle
python3 -m hyperreview track --reconcile
```

The first command persists a metadata-only event before SDK delivery. The second
replays one pending event without inference. The default database/artifact root
matches the server command above; override trusted paths with `--database`,
`--artifacts-root`, `--runtime-python`, and `--spool-root`. A spool cannot silently
switch destinations. Source-bearing bundles stay local; operational receipts
survive their removal. An incomplete/conflicting MLflow record remains pending.

The UI at `http://127.0.0.1:5050` reads the same SQLite database; the delivery
child makes no HTTP tracking requests. Manual traces are retrospective workflow
receipts with absent inputs/outputs. Confirmation updates preview metadata and
displayed status, and does not establish program behavior or authorize a GitHub
comment. For a preview bundle, `track --bundle` re-renders both Markdown views
after tracking confirmation. See [local tracking and recovery](SPECS/12-local-tracking.md).

## Assess a compact preview

After reading `preview-compact.md`, record `ok` or `not_ok` with an optional note:

```sh
python3 -m hyperreview feedback \
  --bundle "$HOME/.local/share/hyperreview/previews/<bundle>" \
  --assessment ok
```

For a correction, use `--assessment not_ok --note "The scope comparison is unclear"`.
An optional `--expected-preview-sha256 <shown-file-hash>` rejects a changed
preview. Each submission creates a separate private local record with exact
revision, result, projection and preview fingerprints. It performs no inference
or network calls, changes no analysis artifact, and exports no notes to
MLflow/Evidently. See [local feedback](SPECS/16-preview-feedback.md).

## Plan publication without GitHub writes

To make an in-progress HyperReview review visible to branch protection that
requires resolved conversations, first prepare and explicitly create a
diff-anchored review-gate comment. Choose an added line in a supported changed
file and provide an expected UTC completion time:

```sh
python3 -m hyperreview review-gate-plan \
  --repo 0al-spec/SpecGraph --pr PR_NUMBER \
  --path path/to/changed-file.py --line 42 \
  --expected-completion 2026-10-19T12:00Z
```

The command only reads GitHub and saves a private plan. Review its exact body
and printed SHA256 values, then explicitly authorize creation of the inline
review thread:

```sh
python3 -m hyperreview review-gate \
  --plan-dir /absolute/path/to/review-gate-plan \
  --expected-plan-sha256 REVIEWED_PLAN_SHA256 \
  --expected-comment-sha256 REVIEWED_COMMENT_SHA256 \
  --authorize-repository 0al-spec/SpecGraph
```

This creates one review comment anchored to the selected changed line. GitHub
returns its permalink. When preparing the completed review preview, pass that
URL to `publish-plan` with `--review-gate-url`; the resulting ordinary summary
comment links back to the review thread. HyperReview never resolves the thread.
The repository owner's “require conversation resolution” rule supplies any merge
blocking; a timeline comment alone does not block merging. Automatic reviews
start and complete independently of whether the actual base branch has that
rule, including intermediate stack branches. New start threads explain this
boundary; HyperReview does not query or change branch protection. The expected
completion time is an operator estimate, not an enforced deadline.

```sh
python3 -m hyperreview publish-plan \
  --bundle /absolute/path/compiled-preview-bundle \
  --expected-preview-sha256 SHA256_OF_SHOWN_COMPACT_PREVIEW \
  --review-gate-url https://github.com/0al-spec/SpecGraph/pull/PR_NUMBER#discussion_rCOMMENT_ID
```

The command validates the exact compact preview and confirmed MLflow receipt,
then reads the authenticated account, live PR eligibility, base/head and
merge-base revisions, and existing comments. It rechecks PR state before saving.
A private `plan.json` records `ready` or `blocked`; `comment.md` contains the
marked comment draft. The command prints SHA256 digests for both files so they
can be reviewed and bound into the later authorization invocation. Exit codes
are 0 for ready, 2 for a blocked plan, and 1 for an invalid input or failed
operation. It makes no GitHub writes. When supplied, `--review-gate-url` must
identify the authenticated operator's HyperReview review comment on the same
PR and pinned head; its permalink is included in the ordinary comment draft.

The CLI and automatic publisher also try one five-second read of check-runs for
that exact head. A separate collapsed CI block supports the architectural
explanation; unavailable, pending or failed checks never block it. The snapshot
is frozen into the publication plan and omitted if the comment has no space.
It reports check-run outcomes, without claiming that a specific `verified_by`
test executed or that architecture conforms. See
[optional CI evidence](SPECS/17-publication-dry-run.md#optional-ci-evidence).

Only the authenticated operator's comment bearing the fixed HyperReview marker
is an update candidate. Duplicate owned markers or an incomplete comment
inventory block planning. Feedback `ok` does not grant publication authority.
A ready plan is a snapshot, not an execution ticket. The one-shot `publish`
command requires the exact plan and comment hashes shown to the operator, plus
the exact repository and `comment` mode. It serializes per PR, repeats live
eligibility/revision/comment checks, and uses a private receipt to recover an
uncertain create or update without blindly appending. It only creates or edits
the authenticated operator's marked issue comment. It never approves, merges,
pushes, or resolves review threads.

```sh
python3 -m hyperreview publish \
  --plan-dir /absolute/path/to/ready-plan \
  --expected-plan-sha256 SHA256_OF_REVIEWED_PLAN_JSON \
  --expected-comment-sha256 SHA256_OF_REVIEWED_COMMENT_MD \
  --authorize-repository 0al-spec/SpecGraph \
  --authorize-mode comment
```

This command performs a live GitHub write when all gates pass. Local and CI
verification use offline fakes; running it against a real PR requires a fresh
explicit operator decision for that exact plan. See [controlled publication](SPECS/20-controlled-publication.md).

## Controlled pilot and local Evidently report

Generate six synthetic boundary cases using the trusted compiler:

```sh
python3 -m hyperreview pilot --compiler /absolute/path/hypercode \
  --compiler-sha256 VERIFIED_BINARY_SHA256
```

The private bundle contains numeric assessments, a reviewer worksheet, a
separate answer key, and an unfilled scorecard. These are hand-authored boundary
fixtures, not measured LLM output or a completed human evaluation. An unchanged
composition deliberately accompanies an approval bypass in one case.

The intended P2 product loop is lightweight: after viewing a preview for their
own PR, a user can mark it `ok` or `not_ok` and optionally leave a note. Each
feedback record is tied to the PR revisions, projection and exact compact preview
shown. The local `feedback` command implements this capture. Comparative accuracy
or review-time studies are optional research, not a product, scheduler, or
publication prerequisite; the current technical reports make no model
superiority claim.

Install the optional reporting environment separately from MLflow:

```sh
python3.13 -m venv ~/.local/share/hyperreview/evaluation-runtime
~/.local/share/hyperreview/evaluation-runtime/bin/python -m pip install -r requirements-evaluation.txt
~/.local/share/hyperreview/evaluation-runtime/bin/python -m hyperreview.evaluation_report \
  --input /absolute/path/pilot-bundle/assessments.json \
  --output-root /absolute/operator/path/evaluation
```

The reporting runtime requires Python 3.12+; Python 3.13 was exercised on macOS
ARM64. Evidently receives only fixed numeric columns, with telemetry disabled
before import. Reports remain local, with no model calls or Cloud upload. Human
accuracy and review time are outside these technical metrics. See [the pilot
subset](SPECS/13-pilot-boundaries.md).

### Link a report to MLflow

Install the optional handoff dependencies in the evaluation runtime:

```sh
~/.local/share/hyperreview/evaluation-runtime/bin/python -m pip install -r requirements-evaluation-tracking.txt
env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin \
  DO_NOT_TRACK=1 EVIDENTLY_DISABLE_TELEMETRY=1 \
  ~/.local/share/hyperreview/evaluation-runtime/bin/python -m hyperreview.evaluation_delivery \
  --input /absolute/path/pilot-bundle/assessments.json \
  --output-root /absolute/operator/path/evaluation \
  --database /absolute/operator/path/mlflow/tracking.db \
  --artifacts-root /absolute/operator/path/mlflow/evaluation-artifacts
```

Run from this trusted repository. Delivery regenerates the report from validated
numeric assessments, then logs selected artifacts and numeric summaries in a
separate local evaluation experiment. Arbitrary report files cannot be supplied
for upload. Failed delivery leaves the local report available; another explicit
invocation may create another run. There is no durable evaluation retry outbox.
See [evaluation handoff](SPECS/14-evaluation-handoff.md).

### Compare reviewer revisions on frozen PRs

The [controlled reviewer evaluation](SPECS/28-controlled-reviewer-evaluation.md)
uses native MLflow GenAI custom scorers and Evidently reference/current reports.
The [versioned suite](evaluations/reviewer-v4.json) includes four real PRs,
including a negative caller-attribution example paired with positive coverage.
It separates source-selection experiments from prompt comparisons, validates
sealed artifact lineage and records missing coverage. SDKs receive numeric
witnesses and digests only. Human acceptance remains `ok`/`not_ok`; there is no
model judge, inference, GitHub write or additional publication gate.

The [review-derived corpus](SPECS/29-review-corpus.md) freezes feedback and
source-bearing observations before reviewer changes. Its [v1 manifest](evaluations/review-corpus-v1.json)
contains four development model cases and a separate validator group; private
packets retain actual bytes, not live source paths. `review_corpus capture`
creates candidates, and `review_corpus suite` exports curated model cases.
The [v2 manifest](evaluations/review-corpus-v2.json) adds a separate
provider-grammar regression from SpecGraph #804; its synthetic witnesses are
not reconstructed model responses. The [v3 manifest](evaluations/review-corpus-v3.json)
also preserves a synthetic evaluator control for abbreviated caller names.
Metric `review-witnesses-v4` can qualify these names from cited complete source
without changing literal callee alternatives. The
[rescore receipt](evaluations/results/2026-10-26-caller-identity-v1.json) records
47 saved outputs evaluated without new inference; original scores remain intact.
Use comparison axis `model` to vary model identity under an identical sealed
request, profile, effort, runtime, compiler and configured budget. Historical
Luna output is useful evidence, but cannot serve as a model-only baseline for
a candidate on a changed prompt or harness. No blind holdout exists yet.

## Architecture validation

[GitHub Actions](.github/workflows/hypercode-validation.yml) builds Hypercode
at the pinned source revision using `Package.resolved`, then checks all seven
profiles on PRs and pushes to `main`. It also checks rejection of an invalid
concurrency value and semantic diff behavior. Emitted IR and backend diff are
retained as CI artifacts. Controlled paired projections also exercise the runtime
compiler boundary. These checks do not establish unattended worker behavior.

Run the same check locally after building the sibling Hypercode repository:

```sh
python3 tools/validate_architecture.py --hypercode ../Hypercode/.build/debug/hypercode
```

The required check name, if enabled in branch protection, is
`Hypercode architecture`. Updating the compiler requires reviewing the pinned
SHA in the workflow. Runner tool versions are logged; `macos-latest` is a moving
runner image, not a fully reproducible operating-system/toolchain pin.

## License

[MIT](LICENSE). The license covers these specifications and examples as well as
future project code. Hypercode remains an external dependency with its own
[licenses](https://github.com/0al-spec/Hypercode#license).

## Project code quality

[SpecificationMetrics](https://github.com/SoundBlaster/SpecificationMetrics)
collects S/U adoption, Python LOC, cyclomatic complexity and cognitive complexity
for `hyperreview/`. Tests and development tools have separate roles. CI uploads
revision-bound JSON/SQLite observations; it does not enforce a ratio threshold.
These code observations do not measure the accuracy of generated explanations.

See [setup, local history and comparison](quality/README.md) and the
[quality integration contract](SPECS/19-specification-quality.md).


## Optional private-preview worker

Use `worker-config --private-preview --allow-cloud-source` with explicit native
Codex/compiler paths and SHA256 pins to prepare a v2 config. One due tick collects
a request; a later tick runs isolated generation and compilation into a private
preview. Status exposes the result path without publishing it. Failed or
interrupted jobs do not automatically resend source to the model.

The generated `com.hyperreview.preview` LaunchAgent is separate from the default
intake-only service and requires reviewing its config before installation.
See [configuration, limits and recovery](SPECS/23-worker-private-preview.md).

## Optional automatic comment publication

Create a standing repository-scoped grant for an existing private-preview config:

```sh
python -m hyperreview publication-worker-config --preview-config ABS_CONFIG \
  --authorize-repository 0al-spec/SpecGraph --authorize-mode comment
python -m hyperreview publication-worker-tick --config ABS_PUBLICATION_CONFIG
python -m hyperreview publication-worker-status --config ABS_PUBLICATION_CONFIG
python -m hyperreview publication-worker-launchd-plan \
  --config ABS_PUBLICATION_CONFIG --python ABS_PYTHON
```

The separate `com.hyperreview.publish` service snapshots validated private output,
confirms metadata-only MLflow tracking, and uses the existing fresh-revision broker
to create/update one owned HyperReview comment. It never invokes a model or merges
a PR. Interrupted writes reuse their exact saved plans; failures have a bounded
retry budget. Review and install the generated plist to enable scheduling.
See [standing grants, recovery and retention](SPECS/24-automatic-publication.md).

## Optional automatic review-start threads

Add `--authorize-review-gates --review-gate-repository OWNER/REPO` to an explicitly
configured private-preview worker to create a v3 configuration. An owned inline
thread announces the start and ETA before inference; successful completed
analysis resolves that thread. Terminal failures also close the tool's own thread
after a clear notice that no review or approval was produced. ETA expiry alone
does not release the gate. Repository rules must require
conversation resolution for this to block merge.

The ordinary publisher links its review summary back to the start thread.
After confirmed publication it also posts a short summary link in that completed
thread. Retained completed deliveries can receive the link without rerunning
analysis. Uncertain notification writes are reconciled without duplicate posts.
This separate grant cannot resolve manual gates or other review discussions.
See [configuration and recovery](SPECS/25-automatic-review-gates.md).
