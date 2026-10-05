# Local HTTP inference milestone

This layer consumes a prepared request and produces a model-proposed result
plus a sanitized invocation receipt. It does not establish program behavior,
produce validated Hypercode IR, or authorize GitHub publication.

## Trusted configuration and transport

Provider, model, endpoint, timeout, context budget, and output-token limit come
from the operator invocation. Supported profiles are LM Studio (`/v1`) and
Ollama (`/api`) over HTTP to the literal loopback addresses `127.0.0.1` or `::1`.
Userinfo, query strings, fragments, remote hosts, proxies, and redirects are
rejected. The adapter uses direct HTTP connections and does not expose tools,
credentials, subprocesses, source checkouts, or a tool execution loop to models.
It never downloads models or silently falls back to another endpoint/provider.

The complete request is revalidated at transmission, including source digests,
known sensitive-content patterns, and fixed application metadata. Instructions
and the result schema come from HyperReview; source strings remain untrusted
data. The result schema binds the request digest and constrains source-reference
choices. Local result validation remains authoritative for semantic constraints
that a provider's JSON Schema implementation cannot establish.

An optional navigation message contains bounded same-path unified diffs derived
from the validated selected sources. It is also untrusted user-role data and
keeps the complete request unchanged. Individual diffs are capped at 1024 UTF-8
bytes with a truncation flag; the serialized comparison message is at most 2048
bytes and may omit later pairs. Source IDs identify both sides, and final-newline
flags preserve that distinction in normalized displayed lines. Rename/different
path records are not paired. The supplement is omitted if it cannot fit together
with the largest fixed repair instruction; every actual call still runs preflight.
Ambiguous same-side paths are skipped. Diff computation only accepts pairs up to
8192 combined UTF-8 bytes and at most 256 lines per side; larger sources remain
in the complete request. The shared inference deadline starts before comparison
preparation, and the next transport checks its remaining budget.

The current `composition-v6` prompt requests
`hyperreview.composition-plan.v2` structured nodes. HyperReview validates this
plan and deterministically converts it to canonical `hyperreview.result.v2`
with paired `.hc` projections and an identity map. The generated bundle keeps
the original `composition-plan.json`, the converted `result.json`, and a
sanitized receipt; these stages do not compile or endorse the proposal.

LM Studio may be explicitly configured with `--instruction-role developer` for
models such as gpt-oss; the default remains `system`. The chosen role is retained
in the local generation receipt. Ollama permits only `system`. This choice never
changes source-data trust or permits tools and has no automatic role fallback.

## Bounds and receipts

Context preflight uses the actual UTF-8 provider encoding for messages/schema
(without ASCII-escaping Russian instructions), plus output tokens
and a template reserve. It is a guard, not an exact tokenizer count. The operator
must configure a context no larger than the loaded model's context; an oversized
request fails before transmission. HTTP request/response bytes and total
invocation time are bounded. Non-success responses, malformed JSON, wrong model,
tool/function calls, and incomplete generation are rejected without replaying
inference or following server-provided instructions.

A well-formed provider plan that fails local composition validation gets at most
one regeneration using the original filtered request and a fixed diagnostic
code, a fixed explanation and the allowed source IDs for each side derived from
the validated schema. Repair feedback never copies arbitrary validator text, model output or
source instructions into trusted instructions. Each call gets the same schema,
provider, role and context preflight; both calls share one total timeout.
Transport/envelope, malformed-JSON, model-identity, tool-call and truncation
failures are terminal and do not trigger regeneration. The adapter never edits
returned refs, IDs, parents or side membership to make a plan pass.

The receipt records provider/model/endpoint, elapsed time, request and profile
versions, and available numeric usage. Missing counts and model revisions remain
unavailable rather than zero or invented values. Attempt counts, fixed repair
codes and per-attempt plan fingerprints are recorded; usage is aggregated only
when every attempt supplies it. Raw prompts, source, responses,
and server error bodies do not enter the receipt. Full local proposed results
remain in private operator-managed bundles and are not MLflow artifacts.

## Evidence and limits

Offline fixtures cover wire shapes, input/output validation, local-only policy,
redirect/size/deadline bounds, and unavailable metrics. A live readiness probe on
this Mac used LM Studio's existing local `openai/gpt-oss-20b` model at context
8192, concurrency 1, with a 600-second idle TTL. A tiny controlled JSON request
returned the expected object with a normal completion; it did not include PR
source and does not establish architecture interpretation quality.

Known credential filtering is heuristic. A literal loopback address prevents
this client from choosing a remote destination; it is not an attestation of the
server or its loaded model. The operator must verify the local provider's own
deployment and avoid enabling external integrations for these inference calls.
Codex remains unavailable until its separate process/filesystem/instruction
boundary is verified.

## Official protocol references

- [LM Studio structured output](https://lmstudio.ai/docs/developer/openai-compat/structured-output)
  defines schema-constrained `/v1/chat/completions` and response content.
- [Ollama chat API](https://docs.ollama.com/api/chat) defines `/api/chat`, JSON
  Schema `format`, completion/usage data, and non-streaming configuration.

Next: validate proposed `.hc` with the pinned Hypercode compiler, assemble the
paired IR and diff, and render an explanation with explicit evidence scope.
