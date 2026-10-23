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

Relationship rows are bounded selections, not exhaustive inventories. The compact
view presents the selected `.hcs` properties per side without subtraction; a
missing row does not mean its relationship was removed. Identical selections
can share one display. The exact compiled sheets remain available with their
evidence comments; the renderer never copies a claim onto an uncited side.
The first screen uses Hypercode as the explanation: a composition/diff and
nonempty relation selections. Prose summaries, tables, source links and
qualifications share one collapsed disclosure, including full empty sheets.
The visible sketch/revision labels retain the inferred and pinned scope.

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

Live providers use `hyperreview.composition-plan.v3`, prompt `composition-v19`
and reviewer profile v13. The relationship vocabulary is `depends_on`, `calls`,
`shared_contract`, `data_flow`, `requires`, `available_when`, `reuses_rule`, and `verified_by`.
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

A fresh generation requires a fresh request bound to profile v13. Old requests
are not silently upgraded; their original pinned profile/code or retained
rendered artifacts remain the historical interpretation. Already sanitized
composition-v10 tracking events remain replayable without accepting old
inference requests as current. Generation fingerprints change through the
existing composition/profile/render pins. Publication still requires the
existing compiler/reference checks, tracking receipt and live revision gate.

### Verification-path changes

For additions of tests, documentation or specification bindings, profile v13
first inspects supplied declarations linking obligations to checks. When the
main change adds another verification path to an existing responsibility,
prioritize that declared `verified_by` delta over secondary loader/data-flow
edges. Select the obligation owner and its complete authored ancestor chain,
omitting unrelated branches without flattening containing owners.
The `.hc` composition can remain unchanged. Preserve supported earlier
bindings, add the new complete literal target only on its declared side, and
keep the six-relation budget. Do not add an edge without its declaration.

Preserve the declaration's target granularity: a complete test-file path or
check ID is valid when explicitly linked to the obligation; `file::symbol` is
not required. Do not invent symbols or infer bindings from file coexistence.
The existing literal same-side evidence check applies to all these targets.

Sharing a fixture/corpus does not imply identical client profiles or behavior.
`verified_by` establishes a declared binding, not execution, passing or complete
coverage. Scope execution notes in source documentation to the described local
environment/revision. Optional publisher CI observations stay outside the model
request and never gate architecture explanation or publication. Sanitized
composition-v18 tracking events remain replayable; their requests/results are
not silently promoted to the current profile.

This increment generalizes semantic instructions and output only. The bounded
input selection changes in G2 and the pinned cross-example replay in G3 remain
separate work. No Rust parser or repository-specific reviewer is introduced.

## Source-established role names

Profile v9 / prompt v15 strengthens name reuse after the Hunter #22 replay
renamed the authored root `HunterPrimitives` to `FilesystemAcquisition`. A compact
projection preserves the spelling of represented roles, including roots and
shared owners; omitting unrelated children does not justify a new vocabulary.
Names are chosen from the map appropriate to the reviewed scope. Proposed or
target maps must not silently rename a current implementation projection.

The represented roles retain their authored containing paths. Omitting unrelated
branches does not permit grafting a shared capability under its caller. A caller
role that persists after delegation remains separate from the provider; use
`.hcs` connections to explain delegation instead of manufacturing a rename/move.
An interpretation that disagrees with the authored composition must explicitly
describe the discrepancy and its implementation evidence.

Real source renames retain the corresponding names on each revision. A new
responsibility, deliberate rescope or necessary wrapper can use an inferred
name, with an explicit explanation of the scope difference and relevant existing
roles. Missing or ambiguous correspondence remains a stated limitation. Matching
names do not establish identity, authority, behavior or semantic equivalence.

The provider schema descriptions repeat this guidance at `before_type`,
`after_type` and `reason`. This is model guidance, not a new name-validation gate,
schema field or automatic alias substitution. No repository/language vocabulary
is embedded in the implementation. Saved evidence can prepare a fresh v9 request;
v8 generation outputs are not relabelled or edited. Already sanitized v14
tracking events remain replayable alongside earlier legacy versions.

## Ground the connection, not just its endpoints

Profile v10 / prompt v16 strengthens the common relationship guidance after a
private replay inferred a portable path's dependency on an optional backend
from documentation that merely described both capabilities. Every selected
edge must have same-side evidence for its direction and kind. A declaration
must declare that connection; implementation analysis must identify the relevant
call, import, wiring, transfer or constraint. The explanation briefly names that
support and any relevant condition.

Containment, coexistence and availability alone do not establish a dependency.
An optional dependency is still valid when its direction and condition are
supported. `available_when` runs from the gated capability to its actual
predicate, with relevant platform/feature conditions. A configuration where A
enables B does not establish that A is available when B is independently enabled.
`shared_contract` needs an actual common interface/result/schema and inspected
sharing sites (a producer and consumer suffice), rather than a feature label or
a single producer's API.
Scope exclusions can constrain an interpretation. A disclaimer about missing
integration evidence does not make an unsupported edge suitable for output:
omit it and state the specific unknown in the summary or limitations.

The trusted profile and provider-schema descriptions carry the same guidance
across languages and repositories. Plan v3, request v5, result v2, relationship
vocabulary, compiler checks and rendering remain unchanged. This is a generation
instruction, not deterministic semantic validation or a new merge gate. Saved
outputs retain their original identities; fresh requests bind profile v10.
Already sanitized v15 tracking events remain replayable.

## Preserve call paths and specific knowledge gaps

Profile v11 / prompt v17 addresses the SpecGraph #785 replay's unsupported
shortcut from an adapter to a policy invoked by its resolver. A `source_analysis`
`calls` row describes one immediate invocation. For A → B → C, selected rows
preserve the supported steps and cite each actual caller's callsite. Intermediate
operations do not require extra tree nodes. Within the existing six-row bound,
select fewer useful edges rather than collapsing a delegation boundary; a source
definition, import or prose flow alone is insufficient to establish a direct call.
The architectural owner stays in `owner_id`; it does not supply a fictional
concrete caller name.

Compact node selection should expose the change's central architectural
mechanism. A source-bound diagnostic may need source acquisition, resolution and
report responsibilities; its policy names alone need not explain that mechanism.
This is conditional guidance, not a required pipeline-shaped tree or call graph.

Limitations compare the supplied path/content inventory and omission ledger.
Supplied tool tests and unavailable referenced target tests are different facts.
Name the latter's actual paths/symbols and inspect each target independently;
a supplied implementation must not be bundled with missing bound tests/policies.
An omission ID is not supplied content. Distinguish partial source, missing
comparison and unobserved execution. Do not claim that an entire category is
missing when relevant files were supplied.

The Codex prompt repeats a compact supplied-source inventory after the complete
request, retaining source IDs, sides, paths and line ranges. It is derived only
from validated request records, carries untrusted data labels, and adds no
source collection, symbol inference or execution claims. The complete original
request remains unchanged; existing prompt byte limits still apply. Other
providers retain the shared profile guidance without this Codex prompt envelope.

These are shared generation/schema-description instructions, independent of
repository, language or framework. Plan v3, request v5, result v2, relationship
vocabulary and rendering are unchanged. Compiler/reference checks still do not
prove that a call edge is semantically true. Fresh requests bind v11; retained
v10 outputs are not edited/relabelled, and sanitized v16 tracking events remain
replayable. This change adds no new semantic validation or merge gate.
