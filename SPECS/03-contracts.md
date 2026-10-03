# Data and lifecycle contracts

## Evidence pack

**HR-DATA-001.** Each analysis input MUST identify the repository, PR number,
GitHub author login, base/head repository identities, `base_sha`, `head_sha`,
and `merge_base_sha`. The source change is `merge_base_sha` to `head_sha`;
base-branch advancement invalidates the corresponding job identity.

Selected source snippets MUST include revision, path, line range, and content
digest. PR descriptions and comments MUST be marked as untrusted authored text.
The pack MUST enumerate included files, omitted files, omissions caused by
limits, and source-read failures. Input selection MUST exclude credentials and
operator files. Symlinks and paths escaping the snapshot MUST NOT be followed.

CI observations MUST include check identity, result, checked revision, and
retrieval time. They MUST NOT be attached to a different revision or converted
into claims broader than the check establishes. The worker does not run PR code.

## Projection and claims

**HR-DATA-002.** A result MUST contain `before.hc`, `after.hc`, and an identity
map tying architectural IDs to revision-specific source references and the
reason for each mapping. Both versions MUST use the same abstraction profile.
Renames, splits, and merges require explicit identity decisions; name similarity
alone is insufficient. Ambiguous mappings MUST be reported rather than hidden
as additions/removals. No implementation-to-architecture one-to-one mapping is
assumed. Source relations omitted from the tree MUST remain available as evidence.

**HR-DATA-003.** A claim record MUST contain an ID, text, evidence status,
affected architecture IDs, source references, scope, and limitations.
`declared` means a statement from a named architecture/policy source;
`resolved` means deterministic output of a pinned resolver invocation;
`observed` means a source fact, check, or trace with a named method;
`inferred` means an interpretation proposed by a model. Unknown coverage MUST
be explicit. References MUST exist in the evidence pack at their stated
revision. Existence of a reference does not prove semantic entailment: inferred
responsibilities remain labelled, and substantive correspondence is evaluated
in the pilot. Automated validation MUST reject dangling references and claims
whose evidence class contradicts their provenance.

## State and recovery

**HR-DATA-004.** A job identity MUST include repository, PR, base/merge-base/head
revisions, evidence digest, and policy, provider/model, prompt, schema, and
abstraction-profile fingerprints. Persisted states are `queued`, `collecting`,
`analyzing`, `validating`, `ready`, `publishing`, `completed`, `failed`, `skipped`,
and `stale`. A completed preview and a completed publication MUST record their
delivery mode separately. Retries MUST be bounded and MUST NOT discard the
record of failed attempts. Malformed model output gets at most one repair
attempt within the original time/input budget, then fails without publication.
Process interruption MUST release or recover expired job leases without running
two jobs simultaneously. Unchanged completed jobs MUST NOT be regenerated.

**HR-DATA-005.** A local result bundle MUST include the evidence manifest,
before/after `.hc`, emitted v2 IRs, semantic diff, identity map, claim ledger,
Markdown preview, and run metadata including MLflow experiment/run/trace IDs
and tracking-delivery status. Output validation MUST finish before a
result becomes `ready`. Schema versions and Hypercode version/revision MUST be
pinned. Operator-controlled paths store results; model text MUST NOT choose
filesystem paths. A structurally invalid projection MUST NOT be presented as a
validated Hypercode artifact.

## Publication

**HR-DATA-006.** Publication MUST update at most one ordinary explanatory comment
per PR using a stable tool marker scoped to repository and PR. The body MUST
identify the analyzed base/head revisions, interpretation status, omissions,
and links to supporting source. It MUST NOT masquerade as a GitHub approval.

Immediately before publication, the broker MUST recheck author, repositories,
PR state, authorization, and base/head revisions. A known stale job MUST NOT be
published. GitHub comment writes and PR pushes are not atomic; a post-write
recheck MUST mark the comment stale and queue a new analysis if revisions
changed during publication. This detects a race; it does not guarantee a
permanently current comment after future pushes.

If a write response is lost, the broker MUST recover by finding its marker and
recording the comment ID before retrying. It MUST NOT blindly append another
comment. Concurrent publishers MUST be serialized through the state store.
