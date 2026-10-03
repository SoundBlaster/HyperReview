# Provider-neutral model contract

This P1 layer prepares bounded source data and validates the model's proposed
result shape. It does not itself invoke a provider, parse Hypercode, establish
isolation, or produce a completed review bundle.

## Request boundary

`prepare_request` consumes a `hyperreview.evidence.v1` pack and verifies its
digest, source content digests, pinned revisions, sides, and initial operator
eligibility policy. A local digest is an integrity check, not a signature or a
fresh GitHub authorization. Intake metadata must still be rechecked by a future
publisher.

Only explicitly selected metadata and source fields enter
`hyperreview.request.v1`. Extra pack properties, CI logs, PR descriptions,
credentials, endpoint settings, and delivery controls do not enter the request.
Reference IDs identify source records by revision, path, and content digest.
Requests carry an origin evidence digest, prompt/profile versions, omissions,
coverage limits, and a request digest binding subsequent output to those inputs.

Operator-selected paths and a source-byte budget may narrow the input. Records
are omitted whole and omissions are disclosed; no source text is silently
truncated. An empty source slice fails before inference. The final encoded
request remains limited to 262144 bytes. Backend context limits impose an
additional bound, even when the evidence pack fits its byte limit.

Sensitive paths, instruction files, and recognized credential patterns are
excluded. Detection covers known private-key/token/literal-credential forms;
it cannot establish that all secrets have been recognized. A provider layer
must keep credentials outside inference, use a verified local endpoint with
no tool loop, and reject unauthorized destinations. Filtering is not a reason
to permit a cloud fallback or upload full requests to MLflow.

Source content remains explicitly `untrusted_source_data`. Strings requesting
tool execution, changing the prompt, or providing model settings are source
data. The application supplies the instructions, schema, endpoint, model,
resource limits, and output paths.

## Proposed result boundary

`hyperreview.result.v1` contains the bound request digest, before/after `.hc`,
identity mapping, claim records, summary, and limitations. The validator rejects
unknown fields, invalid types, over-limit strings/lists, duplicate identities,
dangling references, references with a mismatched before/after side, and claims
about unmapped architectural IDs.

All claims in this model-generated result are `inferred`. A model cannot promote
its interpretation to `observed`, `resolved`, or `declared` by setting a field.
Those evidence classes require separate deterministic or authoritative sources
in later artifact assembly. Syntax validation and semantic IR comparison also
remain separate; successful result-shape validation does not mean that the
proposed `.hc` parses or that its responsibilities match the source.

The provider-facing JSON Schema supplies structural constraints. Local
validation additionally checks request binding, identity uniqueness, provenance,
and side-specific references; schema-constrained generation alone is insufficient.

## Next layer

Implement LM Studio/Ollama HTTP inference with trusted loopback-only settings,
bounded responses/deadlines/context budgets, no redirects or proxies, and no
tool execution. Verify readiness with a controlled fixture before analyzing a
selected source slice from a real PR.
