# Worker: isolated generation through a private preview

This increment extends the intake worker with an explicit, separate v2 config.
The optional [v3 automatic review-gate contract](25-automatic-review-gates.md)
adds separate standing thread authority; the v2 boundary below is unchanged.
A due tick performs **one** action: collect one request, or consume one retained
request through isolated Codex, Hypercode compilation and private Markdown.
It does not publish a comment, create a review gate, deliver MLflow data, or
approve/merge a PR. `preview_ready` means structurally validated private output;
claims remain inferred and tracking remains `not_started`.

## Configuration and authority

`hyperreview.worker-config.v1` keeps its closed intake-only schema and behavior.
`hyperreview.worker-config.v2` adds a required `preview` object with exactly:

- `allow_cloud_source: true`, an explicit standing acknowledgement for this
  selected worker/repository configuration;
- absolute native `codex_executable` and pinned `codex_sha256`;
- absolute non-symlink `compiler` and pinned `compiler_sha256`;
- `model`, `reasoning_effort` (`low`, `medium`, `high`), and `timeout_seconds`
  (30–300, default 180 from the configuration CLI).

The CLI requires `--private-preview --allow-cloud-source` plus both executable
paths and hashes. Unknown fields, wrapper/alternate-provider options, disabling
isolation, missing pins and false acknowledgement are rejected. Both executable
pins are checked before any inference. The native Codex receipt must match the
expected fingerprint and outer isolation mode. There is no fallback provider.
The existing author/account, open/non-draft, same-repository and format allowlist
checks still apply. PR content cannot choose settings or executables.

V2 defaults to a separate `preview-worker` state root. Its generated LaunchAgent
uses `com.hyperreview.preview`; generating the plan does not install it or alter
an existing `com.hyperreview.intake` service. Review the config, pins, selected
repositories, operating system/CLI isolation evidence and generated plist before
installation. Config creation authorizes no publication. Use separate state roots
for independently running intake and preview timers, so they do not compete for
the same persisted poll time.

## Identity, serialization and recovery

The existing owner-private process lock covers discovery, intake, generation,
compilation, journaling, artifact writes and expiry. A second tick returns `busy`.
Polling still cannot bypass the configured interval. Prepared requests have
priority over further collection, so a continuous intake queue cannot starve
preview work. A newly collected request is processed on a later due tick.

A preview job key binds the intake candidate, request/handoff digests, trusted
settings, native Codex/compiler pins, model/effort and pipeline/profile code.
The SQLite `preview_jobs` / `preview_events` tables store only identities,
states, times, fixed failures, provider-attempt metadata and artifact digests.
They contain no source, prompts, model prose or credentials.

`queued → analyzing → preview_ready` is the success path. A queued job interrupted
before entering the pipeline resumes the same key only while its committed
execution count is zero. A missing retained request makes it terminal without
contacting the model. Before entering the
pipeline, `analyzing` and its consumed execution are committed durably. Ordinary
failure becomes terminal `failed`; an interrupted `analyzing` job becomes
`failed/interrupted_no_replay` on the next due tick. The same job key is never
automatically retried, even if its bundle is missing or expires. Codex may still
perform its existing one bounded local-validation regeneration (1–2 provider
attempts within one deadline). An uncertain cloud failure is not evidence that
no request occurred; failed jobs retain unknown provider-attempt counts.

Settings/code/revision changes create a distinct identity. Old jobs become
stale. Reactivating an exact old identity does not reset its execution budget.
There are at most 2048 retained preview job receipts; reaching capacity stops
preview inference and requires an explicit retention/policy decision. Receipts
are not evicted to permit another source transmission.

Eligibility and exact base/head are checked before generation and after the
complete pipeline. Each observation uses a new GitHub client with its own
30-second deadline, independent of the earlier discovery client and model work. A closed/draft/foreign-author or changed PR becomes stale;
no ready preview is saved for it. This is a pair of live observations, not an
atomic GitHub lock: a PR can change immediately after the final check. Every
future publication path must still perform its own fresh revision check.

## Execution and outputs

The native Codex path always uses `isolate_process=True` and its external
Seatbelt + bounded OpenAI CONNECT proxy. GitHub credentials remain in the broker.
Unsupported platforms/isolation/login failures stop. Login refresh remains
outside the read-only login boundary; see [the isolation contract](18-codex-generation.md).
The configured shared deadline covers pin checks, model generation, compiler
work and rendering. Generation uses at most 120 seconds; compilation uses the
remaining whole-second budget, at most 120 seconds. Deadline expiry is terminal.

A successful private UUID bundle under the worker's `previews/` contains the
usual paired `.hc`, IR, diff, request/result, compiler/generation receipts,
evidence, composition plan, metadata and both Markdown previews (14 files).
Its full file-hash manifest is journaled. Status validates private paths and the
manifest before presenting a preview; it does not infer again or contact GitHub.
It lists at most 32 current-settings previews with their last revision-check
time. The bundle is suitable for later ordinary tracking and human assessment;
it is not a publication authorization or a claim of semantic correctness.

Preview expiry runs on due v2 ticks, removes owned UUID bundles older than seven
days, and preserves job receipts/digests. It includes partial orphan bundles left
by a crash between file and journal writes, rejects symlinks/unexpected files,
and never deletes arbitrary supplied paths. A crash after saving a bundle but
before committing its journal reference leaves an orphan for expiry, not a new
model attempt. Terminal receipt counts include expired outputs; availability
is given by the `previews` list, not the historical counts.

Hard process termination cannot prove cancellation of already accepted remote
inference. The journal prevents replay; the independent egress proxy has its own
absolute lifetime. The worker does not promise remote exactly-once execution.

## Commands and acceptance

```sh
python -m hyperreview worker-config --repo SoundBlaster/SessionMonitor \
  --private-preview --allow-cloud-source \
  --codex-executable ABS_NATIVE_CODEX --codex-sha256 SHA256 \
  --compiler ABS_HYPERCODE --compiler-sha256 SHA256
python -m hyperreview worker-tick --config ABS_CONFIG
python -m hyperreview worker-status --config ABS_CONFIG
python -m hyperreview worker-launchd-plan --config ABS_CONFIG --python ABS_PYTHON
```

`preview_failed` and `preview_capacity_reached` return CLI exit 1. `preview_stale`
is a safe terminal observation and returns 0. Logs/status expose fixed failure
codes, counts, hashes and private artifact paths only. They never claim zero
inference after an ambiguous failure.

Offline fixtures cover legacy compatibility, forced isolation and pre-inference
pins, deadline and receipt rejection, one job per tick, deduplication, stale
revisions, terminal/interrupted jobs, expiry, bundle tampering, settings changes,
capacity and separate LaunchAgent intent. Operational model/real compiler proof
is recorded separately from these fixtures and does not enable a live timer.
