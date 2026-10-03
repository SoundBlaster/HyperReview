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

## Bounds and receipts

Context preflight uses a conservative serialized byte budget plus output tokens
and a template reserve. It is a guard, not an exact tokenizer count. The operator
must configure a context no larger than the loaded model's context; an oversized
request fails before transmission. HTTP request/response bytes and total
invocation time are bounded. Non-success responses, malformed JSON, wrong model,
tool/function calls, and incomplete generation are rejected without replaying
inference or following server-provided instructions.

The receipt records provider/model/endpoint, elapsed time, request and profile
versions, and available numeric usage. Missing counts and model revisions remain
unavailable rather than zero or invented values. Raw prompts, source, responses,
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
