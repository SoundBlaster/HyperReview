# Structured composition generation

Prompt `composition-v4` asks a local model for
`hyperreview.composition-plan.v1`, not raw `.hc` and a separately authored
identity map. The provider-neutral result remains `hyperreview.result.v1`.
Prepare a new request; earlier prompt versions are rejected rather than silently
reinterpreted.

## One declaration per identity

Each node declares a bare stable ID, nullable before/after responsibility types,
nullable parent IDs, revision-specific source references, and an inferred reason.
An absent type means that node is absent on that side, with no parent or refs.
Before and after are properties of one responsibility, not separate version
objects. A responsibility present in both snapshots keeps one ID; its refs must
be unique and belong to the respective side. A change to fixture documentation
does not by itself imply removal or addition of the predicate responsibility.
Present nodes require source references from that side. Parents must exist on
the same side. Each nonempty side has exactly one root in this compact consumer
profile; Hypercode itself may represent a forest. Duplicate identities, cycles, orphan parents, incompatible source
references, unsupported identifiers, and excess size/depth are rejected.

The adapter derives indentation-based `.hc` and the identity map from these
declarations. Sibling order follows the plan's node order; it is not execution
order. No missing identity, relationship, or source reference is repaired or
invented. Empty sides render as a newline. The compiler still parses, validates,
emits IR, and compares the derived projections through the trusted boundary.

The provider schema uses explicit object fields and nullable scalar types;
a side without any supplied sources has null-only type/parent fields;
conditional graph/side rules are checked locally rather than relying on a
provider's support for conditional JSON Schema keywords. Provider JSON preserves
schema field declaration order so IDs precede parent references; artifact digests
still use canonical sorted JSON.

This is a HyperReview provider adapter format, not a new Hypercode DSL or IR.
Architecture names, grouping, correspondence, and claims remain model
interpretations. Structured output removes duplicated representation; it does
not establish that the interpretation is useful or accurate.

The compact plan has no `claims` field: explanations live in node reasons and
summary, avoiding a separately named claim graph. Canonical results still retain
the claims field, set to `[]` by this adapter, for compatibility with other result authors.

## Diagnostics and practical feedback

Generation bundles retain the original plan as `composition-plan.json`, its
deterministically converted `hyperreview.result.v1` as `result.json`, and
`receipt.json`. The receipt binds the plan digest, provider-schema fingerprint,
canonical-result-schema fingerprint, prompt fingerprint, request, and result.
These source-bearing artifacts stay local by default. MLflow exports only the
existing metadata allowlist.

Compilation produces both `preview.md` (verbose diagnostics) and
`preview-compact.md` (a concise Russian diff, reasons, and source links). After
tracking confirmation, `track --bundle` re-renders both files; the verbose view
shows the confirmed tracking status.

The practical acceptance is a compiled, compact preview that the operator can
mark **ok** or **not ok**, optionally identifying an unclear or incorrect node.
The local `feedback` CLI implements capture
([contract](16-preview-feedback.md)). No independent reviewer or
accuracy/time experiment is required. User feedback does not replace
compiler/provenance checks or separately authorize publication.

## One bounded validation repair

Prompt v4 emphasizes paired responsibilities and source-side invariants. A plan
rejected by local conversion may be regenerated once with a trusted fixed
diagnostic code, a fixed explanation, a schema-derived source-ID catalog and the
same original request. The accepted plan is still model
authored and fully revalidated; the adapter does not deduplicate refs or invent
parents on the model's behalf. Two invalid plans fail without a result bundle.
Both attempts share the operator's timeout; context/byte limits are checked
before each request. Provider transport/envelope failures are not repaired.

Generation receipts retain bounded attempt metadata and repair codes, without
raw invalid plans or error text. This is invocation-local accounting, not a
durable failed-job journal or a new MLflow attempt trace. Earlier request prompt
versions must be prepared again; existing artifacts are not silently migrated.
