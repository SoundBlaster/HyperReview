# Local worker: read-only intake stage

This is the first P4 increment. A bounded one-shot tick discovers eligible PRs,
serializes intake tasks, and saves pinned evidence plus a filtered model request.
The same tick can be invoked manually or by the generated macOS LaunchAgent.
It does **not** run inference, compile projections, deliver tracking, publish a
comment, create a review gate, or approve/merge a PR. `request_prepared` is a
handoff stage, not a completed architectural review or the pipeline's `ready`.

## Trusted configuration

`worker-config` writes an owner-private JSON file with schema
`hyperreview.worker-config.v1`. Its only settings are selected repositories,
poll interval, and an absolute private state root. Unknown keys, duplicate
repositories, symlink traversal, non-private files/directories and repositories
outside the existing intake allowlist are rejected. The author/account and
same-repository/open/non-draft checks remain the existing intake policy; PR data
cannot supply configuration, prompts, executable paths, or output paths.

The interval defaults to 300 seconds, with a supported range of 300–86400.
`worker-tick` also enforces a persisted next-poll time, so invoking it repeatedly
cannot bypass the interval. `worker-status` reads only local state. Both commands
return small JSON summaries; raw source and GitHub response bodies are absent.
Status includes at most 32 recent request handoffs and their private bundle paths.

## Queue and recovery

A nonblocking owner-private process lock covers discovery, collection, journal
transitions, artifact expiry and log rotation. A second process returns `busy`.
The lock is released by the OS when a process exits; it is not a timestamp lease.
An interrupted `collecting` task becomes `failed` on the next due tick.

The SQLite journal is separate from MLflow. Tasks store revisions, fingerprints,
state, attempts, digests and a locally generated artifact UUID; transitions store
only state/time/attempt and fixed failure codes. No source, prompt, credential,
PR title or PR-authored prose is stored in the journal. SQLite uses full sync
and a rollback journal. The worker uses at most 32 pending tasks and 2048 retained
task receipts. Reaching a bound stops further discovery without advancing that
page. Receipts are not silently evicted: removing them explicitly permits fresh
collection and must be an operator action.

Each tick reads one page of at most 30 open PR metadata records per selected
repository. A persisted cursor advances through pages and wraps after a short
page, rather than assuming the first page is the complete inventory. GitHub's
live pagination can shift during pushes/closures; subsequent cycles reconcile
it. It is not an atomic inventory or immediate notification mechanism.

A provisional candidate key includes repository/PR/base/head and the intake
pipeline fingerprint. That fingerprint binds intake/worker/policy code, request
schema, prompt, reviewer profile and abstraction profile. Completed intake for
the same active candidate is not repeated. If an exact stale candidate becomes
eligible again after re-enabling a repository, reverting revisions or rolling
back a pipeline, its retained handoff is revalidated and restored. If the bundle
has expired, collection is queued only within the original two-attempt budget;
re-enabling never resets that budget. A newly observed revision or changed pipeline
makes older tasks stale. Before collection the ordinary collector freshly checks
eligibility and pins merge base; base/head must still match the candidate.
The final handoff also binds merge base, evidence digest and request digest.
This intake identity is deliberately distinct from HR-DATA-004's future full
analysis job identity containing the selected provider/model and compiler.

At most one task is collected per tick. The named SpecificationCore rule
`worker_intake_task_eligibility` permits queued/failed tasks only before two
attempts have been consumed and after their retry time. A failed attempt waits
at least one configured interval. There is no unbounded retry, provider fallback
or inference replay. The intake client's shared 300-second deadline, 30-file and
262144-byte evidence limits and supported-format exclusions remain in force.

## Artifacts and retention

Each successful collection writes `evidence.json`, `request.json` and
`metadata.json` to a private UUID directory below the worker's own `artifacts/`.
Requests use the ordinary secret/path filters and bounded whole-file selection.
Evidence is sensitive local data; filters are not a guarantee of no secrets.
The handoff explicitly records `request_only`, zero model calls and zero GitHub
writes. Manual `generate`, `compile`, `track` and the separately authorized
publisher remain the next pipeline stages.

On due ticks, bundles older than seven days are removed from this owned directory;
the redacted SQLite receipt and digests remain. Expiry includes partial/orphan
UUID bundles left by a crash. It rejects symlinks and unexpected filenames and
never traverses arbitrary paths from source/model data. Artifact inventory is
bounded to twice the receipt limit (at most two attempts per task). A crash
before a bundle is journaled can cause one further collection, within the same
two-attempt budget; it cannot repeat model inference because none occurs here.

The two fixed launchd log files rotate at 64 KiB, keeping one previous file each.
Setup and plan generation pre-create both log targets with mode 0600: launchd
can open/create stdout/stderr files before applying the child process's Umask.
Rotation immediately re-creates the current target with mode 0600 as well.
One terminating tick may append its small status line to the rotated open file.
Retention runs only while the worker executes; stopping the service also stops
expiry. This stage never cleans pre-existing manual preview/tracking directories.

## LaunchAgent plan and installation

`worker-launchd-plan` writes `agent.plist` and installation/unload instructions
in a private bundle. It does not execute `launchctl` or install a service.
The plist invokes an explicit Python interpreter with `-B -m hyperreview
worker-tick --config ABS`. Its working directory and logs use the private worker
state root. It uses `StartInterval`, background priority, a private umask and
`RunAtLoad=false`, with no secret values embedded. Use an interpreter where
HyperReview and its pinned policy dependency are installed; a venv's final
interpreter symlink is supported without replacing its venv path.

Review the generated plist and selected repositories before bootstrap.
Installation is a separate operational step; sleep can delay polling and the
service makes no continuous-availability promise. The generated service is an
intake scheduler. Unattended Codex remains disabled until the installed CLI's
filesystem/process isolation is demonstrated under HR-SEC-003. A scheduler must
not turn the current manual cloud acknowledgement or publication digest flags
into standing authority. No alternative backend is selected automatically.

## Commands

```sh
python -m hyperreview worker-config --repo 0al-spec/SpecGraph
python -m hyperreview worker-tick --config ABS_CONFIG_JSON
python -m hyperreview worker-status --config ABS_CONFIG_JSON
python -m hyperreview worker-launchd-plan \
  --config ABS_CONFIG_JSON --python ABS_VENV_PYTHON
```

The first two commands read live GitHub only in `worker-tick`. A `failed` tick
returns exit 1; `idle`, `busy`, `not_due`, `stale` and `request_prepared` return 0.
Configuration/storage/transport errors return 1 with a fixed sanitized message.

Offline fixtures cover request preparation and deduplication, interval and lock
exclusion, bounded retries, revision changes, interrupted collection, retention
and missing-bundle reconciliation, queue capacity, private configuration, the
pure retry rule and launchd plan arguments. The first manual operational run and
the generated plist establish only this intake path. Sleep/wake recovery,
concurrent-process stress, unattended inference, and full automatic review/
publishing remain separate acceptance work.
