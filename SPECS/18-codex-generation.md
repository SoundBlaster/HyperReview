# Codex generation pilot

The current pilot uses the installed Codex CLI directly. `generate` defaults
to `codex`, model `gpt-6-luna` and reasoning effort `low`, following the operator's
choice after a real selected-source probe. A generic adapter framework is deferred.
The canonical request, composition plan and result contracts remain unchanged.

## Invocation and authority

Codex remains the selected default, but generation requires the trusted operator
flag `--allow-cloud-source` acknowledging source transmission (HR-SEC-004).
Explicit `--provider codex` alone is insufficient. The direct Python API also
requires `CodexConfig(allow_cloud_source=True)`; missing acknowledgement stops
before executable resolution or inference. Receipts record this acknowledgement.
The flag is rejected for local HTTP providers, which do not send source to Codex.

The runner resolves the operator's executable, records its launcher fingerprint,
and starts `codex exec` with an argument array, never a shell command. It uses a
private temporary working directory, read-only sandbox, ephemeral session and
ignored user configuration. Project instructions are disabled with
`project_doc_max_bytes=0`; shell/unified exec, hooks, plugins, apps, browser,
computer, image, agent and other tool features are explicitly disabled, with
web search disabled separately. A bounded `codex features list` preflight selects
the registered `view_image` or older `view_image_tool` disable switch. No unknown
image feature is passed; if neither is registered the invocation stops before
inference. The selected switch is recorded in the receipt, and the preflight
shares the same private working directory, filtered environment and deadline.
The source pack and optional diff are data in the prompt, not executable
instructions or workspace files from the PR.

Only the filtered runtime/authentication environment needed by Codex is retained.
GitHub publication credentials and unrelated environment variables are excluded.
Codex uses the operator's existing authentication; HyperReview does not read,
copy or export its credential contents. Source is sent to the Codex service;
there is no silent switch to another backend on failure.

Read-only alone is insufficient. The runner also rejects tool/action events,
failed turns, malformed event streams, missing completion, nonzero process exit
and absent/mismatched final output. The restricted profile is intended for this
manual pilot; an unattended worker must select the outer process isolation below and
verify its installed CLI and configuration. Event auditing is an additional check,
not a rollback mechanism for already performed actions.

The installed CLI reports its disabled Code Mode host as an error-shaped startup
notice. Exactly that fixed notice is accepted once immediately after thread start
and before turn start. Changed wording, shape, order or repetition is rejected;
the receipt records only a boolean per attempt. The host remains disabled.

## Bounds and validation

Input/schema bytes, combined stdout/stderr, final output and the process deadline
are bounded. The process group is terminated on timeout or output overflow.
Both model attempts share the deadline. CLI/context/output-token flags from the
HTTP path are rejected, since this invocation cannot enforce those token limits.
Codex service limits and usage counts are distinct from local process bounds.

The provider schema removes only unsupported `uniqueItems` from reference
arrays. The original local plan validator still checks duplicate refs, correct
source sides, request binding, absent-side fields, identities and graph shape.
It also applies the compact responsibility naming filter. Canonical JSON and
the provider-neutral result schema are unchanged.

A locally invalid plan may be regenerated once with the fixed code, safe
location/hint and source-ID catalog. CLI/event/transport errors are terminal.
Accepted output is model authored and fully revalidated; the adapter does not
repair source references or rename nodes itself.

## Receipts and downstream stages

Generation produces the existing private four-file bundle and a sanitized
receipt with provider `codex`, requested model/effort, launcher and schema
fingerprints, request/result/plan bindings, available usage and bounded attempt
metadata. Model revision is unavailable unless independently supplied; configured
model identity is not a verified weights revision. Raw events, prompts, source,
CLI diagnostics and credential data do not enter the generation receipt.

Ordinary `compile`, `track`, `feedback` and publication planning consume the same
artifacts. Metadata-only MLflow events recognize `codex`; their model identity
hash includes the requested reasoning effort. Compilation proves structure and
references, not semantic accuracy. Publication and scheduler installation remain
separate stages.

The flags were checked against the installed CLI and the
[official configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference).

## Outer process isolation on macOS

`generate --isolate-process --allow-cloud-source` opts into a fail-closed outer
Seatbelt boundary around **both** the feature inventory and `codex exec`. It
requires `/usr/bin/sandbox-exec` and a native Mach-O CLI. The known npm launcher
is resolved to its packaged native binary without running Node. The actual
binary is fingerprinted before execution, with a separate 512 MiB bound (the
manual launcher path retains its 128 MiB bound). Unsupported platforms,
wrappers, missing private file-based login or policy startup failure are terminal;
there is no unrestricted retry.

The deny-default policy permits system runtime subtrees, the exact native
binary, an owner-private job directory, and the operator's read-only `auth.json`.
It does not grant the whole `/System` tree, which includes a data-volume alias.
The root-owned system public CA bundle is readable and supplied explicitly for
TLS verification; no user Keychain service is permitted. Global file metadata
inspection is permitted; unrelated file contents and writes
are not. The child gets a fresh HOME/CODEX_HOME, no inherited API keys, GitHub
credentials, session state, proxy exceptions or user configuration. A symlink
exposes only the existing login file; HyperReview does not read or copy its
contents. The login and policy paths are protected against child writes. Login
refresh must happen outside this boundary; an expired login may fail and does
not authorize widening access or writing credentials back.

Only the native executable may be executed again; fork and other executables
are denied. Sysctl reads are limited to hardware and named runtime parameters;
process argument/environment inspection is denied. The existing tool disable flags, ignored rules/configuration,
JSONL event audit, output validation and shared deadline remain mandatory.
This boundary is not a VM or protection against a compromised same-user broker,
OS/kernel defects, or an operator replacing trusted binaries/policy files.

The only outbound socket destination is the loopback proxy's selected port.
The credential-free proxy runs in a supervised subprocess and accepts only
CONNECT to `chatgpt.com:443`, `api.openai.com:443` or `auth.openai.com:443`.
It validates all DNS answers as global addresses, connects to those IPs without
another lookup, and rejects IP literals, local/private destinations, credentials
in CONNECT headers and other HTTP methods. TLS remains end-to-end; source and
headers are not logged. The proxy has bounded headers, concurrent connections,
per-direction buffering, total tunnel bytes and lifetime. Teardown stops and
reaps it, including blocked DNS work. This constrains destinations, not which
operations an authenticated client can perform at the permitted provider.

Generation receipts record the isolation mode and policy fingerprint, native
binary fingerprint, OS release, system CA fingerprint and egress policy identity. Manual non-isolated invocations
remain available for compatibility and explicitly record `mode: none` and
`unattended_eligible: false`; their command sandbox must not be presented as an
outer process boundary. The installed intake timer remains intake-only.

The macOS CI job compiles a native canary and exercises syscalls directly:
workspace read/write and proxy-port access are positive controls; unrelated
reads/writes, symlink traversal, policy/login writes, other TCP destinations,
Unix sockets, another process's arguments/environment, fork and shell execution
must fail with permission errors. These
synthetic checks need no real credentials or inference. Linux CI runs deterministic
policy, proxy and compatibility fixtures; it does not claim Seatbelt evidence.

### Observed installed-CLI check (2026-10-19)

On macOS 27.0, installed native Codex CLI 0.156.1 completed the synthetic paired
`Assessment` request with `gpt-6-luna`, reasoning `low`, in one attempt (12,247 ms).
A repeat with the narrowed sysctl policy also succeeded in one attempt (9,518 ms).
The returned plan passed the ordinary local request/result checks. Both feature
inventory and generation used the outer boundary; unrelated home files and
GitHub credentials were not granted. This is an observed compatibility slice,
not a claim about semantic accuracy, future CLI versions or a live PR review.
Earlier probes without the explicit system CA bundle failed to complete; the
successful profile grants only that public certificate file, not Keychain IPC.
