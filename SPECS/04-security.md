# Trust and publication policy

## Eligibility and untrusted content

**HR-SEC-001.** Before reading source for model analysis, require an exact
repository-allowlist match, PR author login `SoundBlaster` in the initial
profile, and equal base/head repository identities. Draft and closed PRs are
excluded by default. Authenticated GitHub account and author-filter settings
are distinct; mismatches MUST be surfaced. Eligibility MUST be rechecked before
publication. PR author identity does not establish the authorship or safety of
every commit; it is a filter, not an execution authorization.

**HR-SEC-002.** PR code, comments, filenames, model output, and documents are
untrusted data. The worker MUST NOT execute PR programs, build scripts, hooks,
package installers, or model-requested commands. PR-supplied `AGENTS.md`, skills,
model settings, endpoint URLs, and prompts MUST NOT become worker instructions.
Policy comes from trusted operator configuration outside the analyzed revision.
Source strings MUST NOT be interpolated into shell commands. Git/file access
must avoid checkout hooks, external diff drivers, submodule execution, and
symlink traversal; deterministic parsing reads source as data.

## Model and credential boundary

**HR-SEC-003.** The model adapter MUST receive only an evidence pack and trusted
analysis instructions. It MUST NOT possess GitHub publication credentials or
access unrelated home-directory data. HTTP providers MUST have no tool execution
loop. A Codex profile MUST disable untrusted project instruction loading,
unauthorized tools, hooks, and connectors and establish the intended filesystem
and process boundary before unattended use. `read-only` is insufficient by
itself: it does not establish that secrets cannot be read or data cannot leave
through permitted tools. If that boundary cannot be demonstrated, the Codex
backend remains unavailable; use the restricted HTTP inference path instead.

**HR-SEC-004.** GitHub reads and writes belong to the broker. Credentials MUST
use the least permissions needed for selected repositories, and MUST NOT appear
in packs, model prompts, output bundles, or logs. Cloud inference MUST require
explicit operator configuration acknowledging that source is transmitted to
the configured provider. Local-provider profiles MUST use loopback endpoints
and locally hosted models; cloud fallback MUST NOT happen silently. Endpoint
and model selection MUST come only from trusted configuration. Availability,
context size, and model capabilities MUST be verified before enabling a backend.

The same data-minimization boundary applies to MLflow tracing and evaluation:
see [HR-TRACK-003](06-mlflow.md#run-and-trace-contracts).

## Publication and operations

**HR-SEC-005.** Preview MUST be the default. Publishing requires explicit
operator authorization for the repository and delivery mode, plus a valid result
and a fresh eligibility check. Setting an `.hcs` boolean alone MUST NOT bypass
this broker check. The publisher may edit only its own identified comment;
it MUST NOT approve, merge, push, resolve reviews, or edit other comments.

**HR-SEC-006.** Audit events MUST record job IDs, transitions, versions, source
revisions, gate decisions, omissions, and publication and MLflow correlation IDs while excluding
secrets and raw model request bodies. Retention defaults to seven days for
local evidence/output bundles; deleting expired artifacts MUST preserve a small
redacted job receipt for deduplication. Operator deletion of receipts may cause
an intentional fresh analysis and MUST be documented.

**HR-SEC-007.** Trusted limits MUST bound polling, concurrency, source files,
input bytes, retries, and analysis duration. Initial values are one concurrent
job, 30 source files, 262144 evidence bytes, a 300-second analysis deadline, and
two model attempts total. Oversized packs MUST record omissions or skip rather
than silently truncate. Provider token limits MUST be checked in addition to
byte limits. Exceeding a limit MUST stop the job before publication.
