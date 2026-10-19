# Structured composition generation

Prompt `composition-v8` combines the shared trusted reviewer profile with
provider instructions and asks a model for
`hyperreview.composition-plan.v2`, not raw `.hc` and a separately authored
identity map. It converts the result to `hyperreview.result.v2`.
Prepare a new request; earlier prompt versions are rejected rather than silently
reinterpreted.

The packaged `hyperreview/reviewer_profile.md` defines the model's bounded
review method: responsibility-level projection, source-only evidence limits,
the structural-only meaning of nesting, and the selector policy. Both local
providers and Codex consume this same file. Requests pin its version and SHA-256;
generation and tracking receipts preserve that identity. The profile is trusted
guidance, not proof that a model followed it or that an interpretation is correct.

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
declarations. An address pairs the role with its stable internal ID. `.hc`
selectors are emitted only if that pinned side contains an `.hcs` file and the
role repeats in that side's projection. Selector presence is derived from the
complete pinned repository trees, never inferred from the selected model
sources. Sibling order follows the plan's node order; it is not execution order.
No missing identity, relationship, or source reference is repaired or
invented. Empty sides render as a newline. The compiler still parses, validates,
emits IR, and compares the derived projections through the trusted boundary;
provenance checks compare role counts when a selector is omitted and exact IDs
when it is present.

For example, with no `.hcs`, the same role stays selector-free even if the
identity map keeps `Assessment#assessment` as its internal address. When `.hcs`
exists and `Assessment` appears twice in one projection, the adapter emits
`Assessment#assessment` and the other role's corresponding ID so HCS rules and
the compiler can distinguish those nodes. A unique role stays `Assessment`
even when `.hcs` exists.

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
deterministically converted `hyperreview.result.v2` as `result.json`, and
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

The prompt emphasizes paired responsibilities and source-side invariants. A plan
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
Each attempt records the SHA256 of the complete system message actually sent,
including bounded repair instructions. The top-level prompt fingerprint names
the attempt that produced the accepted result.

## Responsibility explanations

Prompt v6 and provider-schema descriptions ask for domain responsibilities,
stable IDs and concrete explanations of changed or preserved code. Files,
functions and version containers are not the intended unit of explanation.
One supported responsibility may remain a single node; larger trees require
distinct tasks supported by the selected sources.
The provider schema declares the concise factual explanation before the ID and
types, so a constrained decoder can describe the task before naming its node.
IDs still precede parent references. This changes provider declaration order,
not canonical JSON digests or the provider-neutral result contract.

Comments can explain a stated intent or describe another system, but do not
establish that system's behavior. A documentation-only change should preserve
the responsibility and describe the updated documentation separately from the
unchanged predicate. A changed condition can preserve the same responsibility
type and ID, with the actual difference described in its reason and summary.
Limitations should identify missing evidence specific to the interpretation;
the preview already includes the request's general limitations.

These are generation instructions, not deterministic semantic validation.
Compiler success and source-reference checks do not prove that the model chose
the right abstraction or accurately described its source. Live examples must
be inspected before treating them as useful explanations.

The compact review adapter additionally rejects six generic type labels
(case-insensitive): `File`, `PythonFile`, `Function`, `Module`, `Documentation`
and `Comment`. They describe source containers rather than the responsibility
requested by this profile. The fixed `generic_responsibility` repair hint asks
for the task of the executable code, including unchanged code; comment edits
belong in its explanation. More specific names such as `DocumentationGeneration`
are allowed. This small naming filter does not validate architectural meaning,
and is a consumer-profile rule, not a Hypercode language restriction.
