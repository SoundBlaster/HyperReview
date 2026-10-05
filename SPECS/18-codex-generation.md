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
manual pilot; an unattended worker still needs an operational isolation check
for its installed CLI and configuration. Event auditing is an additional check,
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
