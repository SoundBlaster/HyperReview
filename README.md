# HyperReview

A local PR reviewer that explains architectural changes using illustrative
Hypercode projections, source references, and explicit evidence boundaries.

**Status: manual compiled preview with local tracking.** A Python CLI collects pinned PR evidence,
prepares a filtered request, proposes a result through LM Studio or Ollama,
and validates paired projections before rendering a local explanation.
Metadata-only MLflow delivery and recovery are implemented. Evidently, scheduler,
and publisher remain implementation work. The Hypercode
model describes the proposed full reviewer, not an installed service.

## The pilot

For an eligible PR, collect pinned before/after source data, build a paired
architecture projection with stable IDs, validate the artifacts, and produce
one concise Markdown explanation with a Hypercode diff. Initial operation is
local preview. Publication is a separately enabled mode.

The initial repository allowlist is `0al-spec/SpecGraph` and
`0al-spec/Hypercode`, with PR author `SoundBlaster` and same-repository heads.
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

Requirements: Python 3.10+ and an authenticated `gh` CLI for `github.com`.
Run from this repository; there are no Python package dependencies to install.

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

The pack is bounded to 262144 encoded JSON bytes and 30 logical changed files
(up to two revisions per file). It records exclusions, read failures, and check
coverage. Source-path filtering is a conservative heuristic, not a guarantee
that arbitrary source text contains no secrets. Full local evidence is not yet
approved input for a model or tracking export. No automatic retention or job
deduplication is implemented; manually remove intake directories when no longer
needed. See [the intake milestone contract](SPECS/08-intake-milestone.md).

Run the offline intake checks:

```sh
python3 -m unittest discover -s tests -v
```

[Intake CI](.github/workflows/intake-validation.yml) runs these fixtures without
GitHub credentials, real PR reads, or model calls.

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

## Explicit local inference

Load a local model with an appropriate context using the provider's own tools,
then select that exact API model ID:

```sh
python3 -m hyperreview generate --request /absolute/path/request.json \
  --provider lmstudio --model hyperreview-gpt-oss-20b --context-tokens 8192
```

LM Studio defaults to `http://127.0.0.1:1234/v1`; Ollama defaults to
`http://127.0.0.1:11434/api`. An explicit `--endpoint` must use a literal loopback
IP with the provider's exact API path. There are no redirects, proxy routing,
tools, remote fallback, or automatic model downloads. The invocation has bounded
context, response bytes, and time; `--max-tokens` and `--timeout-seconds` are
trusted operator limits. The configured context must not exceed the loaded one.

Private bundles under `~/.local/share/hyperreview/generated/` contain the request,
proposed result, and a sanitized receipt. The stage is `model_generated`, not a
completed review: the `.hc` strings still require compiler validation and the
interpretation still requires review. No MLflow or GitHub publication occurs.
See [the local inference contract](SPECS/10-local-inference.md).

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
paired projections and IR, semantic diff, proposed claims, receipts, and Markdown.
All model interpretations remain `inferred`. The stage is `projections_validated`;
tracking has not been confirmed and publication remains unavailable. See
[the compiled-preview contract](SPECS/11-compiled-preview.md).

Prompt `composition-v2` explicitly aligns projection IDs and revision-specific
source references. Prepare a new request for this version; older prepared
requests are rejected rather than silently reinterpreted under a changed prompt.

## Deliver local tracking metadata

The core CLI still uses the standard library; tracking runs in a separate
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
comment. See [local tracking and recovery](SPECS/12-local-tracking.md).

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
