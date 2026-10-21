# Structured composition generation

Prompt `composition-v9` combines the shared trusted reviewer profile with
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

The compact plan has no `claims` field. Live providers request the bounded
`relations` extension of the v2 plan; node-only v2 plans remain accepted for
existing callers. `plan_schema(request, include_relations=True)` declares the
extension as required for generation. The default schema keeps the node-only
API available. Conversion stores each relation as an ordinary inferred claim
in the unchanged `hyperreview.result.v2` contract; old node-only plans produce
an empty claims list.

## Relationships outside the containment tree

At most six rows explain adapter/policy calls, typed facts, policy reuse,
obligation bindings, or artifact transfer. Endpoints name source-established
symbols, jobs or obligations, without requiring extra architecture nodes. Each
row identifies one revision side, an existing owner responsibility, a declaration or source-analysis basis, a
Russian explanation, and one to eight unique supplied sources on that side.
Wrong-side, missing and duplicate references are rejected during conversion.
The adapter gives these relationships a Hypercode representation as properties
of the owner in a generated companion `.hcs`. Property names come from a fixed
review vocabulary (`calls`, `uses_facts`, `reuses_policy`, `transfers_artifact`,
`binds_obligation`). Several relationships of one kind on an owner form a sorted
string value. Explanations and source refs remain sheet comments and bound claim
metadata; revision-specific annotations do not enter semantic property values.
This vocabulary is interpreted by HyperReview, not built-in edge
semantics in Hypercode. No new tree nodes are needed just for relationships.

The compiler resolves the `.hc`/`.hcs` pair and checks the resulting property
values before the renderer presents the same bound values in a source-linked
table. Companion contents are retained in the compiler receipt, separately
from the inspected repository's configuration. They are an inferred review
artifact, never accepted intent or a runtime configuration file. The temporary
sheet contains no imports or operator-controlled context overrides.

A repeated role gains selectors when generated companion sheets are present,
even if the inspected repository had none. Both sides receive a companion
(possibly empty) to preserve paired identities when only one has relationships.
Unique roles stay selector-free.

This validation establishes reference integrity only. Spec bindings declare an
obligation; inspected callsites may support an interpretation of implementation;
workflow declarations describe intended job dependencies. None establishes that
a job ran, a rule has no bypass, or all procedural duplication was removed.
Omitted configuration is unknown, and source excerpts cannot establish absence
outside their selected ranges. Name a missing entry point precisely: a missing
Makefile does not imply an absent `run_tests` implementation in supplied Python.

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

Compact node explanations group citations by file path, with one short
before/after version link per file. Exact per-node excerpt ranges remain linked
inside the expanded evidence section. Grouping presentation does not discard
source references or imply that the whole linked file was supplied to the model.

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

## G1 common relationship contract

Live providers use `hyperreview.composition-plan.v3`, prompt `composition-v13`
and reviewer profile v7. The relationship vocabulary is `depends_on`, `calls`,
`shared_contract`, `data_flow`, `requires`, `available_when`, and `reuses_rule`.
The same descriptions apply across stacks: a callee may be a function, service,
syscall or policy; a common type is a shared contract, not proof of shared
behavior. Endpoints need source references, not additional `.hc` nodes.

Live plans always contain `relations` and a nonempty bounded `relation_summary`.
The trusted provider boundary rejects a missing current envelope even if a
backend does not enforce its JSON Schema. When `relations` is empty, the adapter
copies its explanation into canonical result limitations with the fixed prefix
`Связи не сформированы: `. The compact renderer shows that explanation next to
the projection. It remains an inferred explanation, not a formal completeness
assessment. The existing result.v2 shape is unchanged.

Common relation claims use `relation-v2-<kind>-<ordinal>` identities. Companion
sheets decode this vocabulary separately from frozen legacy
`relation-<kind>-<ordinal>` identities. The v2-plan conversion path preserves the
five original relation kinds, labels and property keys. Node-only conversion
remains available for direct callers; live providers require the full current
plan. Saved results are never relabelled or given new inferred relationships.

A fresh generation requires a fresh request bound to profile v7. Old requests
are not silently upgraded; their original pinned profile/code or retained
rendered artifacts remain the historical interpretation. Already sanitized
composition-v10 tracking events remain replayable without accepting old
inference requests as current. Generation fingerprints change through the
existing composition/profile/render pins. Publication still requires the
existing compiler/reference checks, tracking receipt and live revision gate.

This increment generalizes semantic instructions and output only. The bounded
input selection changes in G2 and the pinned cross-example replay in G3 remain
separate work. No Rust parser or repository-specific reviewer is introduced.
