# Stack-independent architecture review

## Status and product direction

This is an intended contract and implementation plan. Current Python policy
hints, source-family filters and relation descriptions do not yet satisfy it.
Hunter #22 exposed these gaps; Hunter and SpecGraph are examples, not semantic
profiles the core must recognize by repository name.

The reviewer explains what changed in a system's responsibilities, boundaries,
architecture decisions and constraints, and which evidence supports that
explanation. Its method must work across languages, platforms and frameworks.
Technology names remain useful evidence about a system, not mandatory concepts
or templates for the reviewer itself.

## Bounded evidence with architecture context

1. Look for relevant existing `.hc` and `.hcs` as a pair. Reuse established roles
   where justified, record revision and authority, and disclose missing context.
   Treat input properties as authored claims; compilation does not prove their
   correspondence to the implementation or promote them to accepted intent.
2. Use architecture documentation, specifications and decision records to recover
   intent, constraints and rationale. These are first-class evidence, including
   in documentation-only changes. Contradictions with code or other documents
   remain explicit. Do not reduce documentation to background prose or allocate
   the entire budget to it at the expense of the implementation being compared.
3. Inspect source and relevant build/dependency/configuration declarations to
   understand implementation boundaries and conditions. Distinguish declared
   configuration, static source analysis and observed execution.
4. Preserve the finite format policy, content/path filtering, source-byte budget
   and explicit omissions. Generality does not authorize arbitrary files or
   secret-bearing settings. Use reviewed format/semantic-family selection,
   not project-specific directory names or unrestricted YAML/JSON admission.
5. If Hypercode is absent or incomplete, infer a labelled architecture slice
   from the other evidence. Never require the repository to adopt Hypercode
   before it can receive a useful review. Do not rewrite authored intent to
   make an inferred implementation appear conformant.

## Composition and relationships

`.hc` remains a compact responsibility composition. The explaining consumer
can express source-supported relationships and conditions in `.hcs`, without
adding execution order or graph syntax to Hypercode core.

The semantic vocabulary must cover dependencies, calls, shared data contracts,
inputs/outputs, boundary obligations and availability conditions across stacks.
Calls may target a syscall, service, function or policy. A shared result type
must not be misreported as reuse of one decision rule. SpecificationCore policy
reuse is one useful specialization of this common model.

Each relationship needs a named owner, exact revision-bound source references,
a stated basis and disclosed gaps. Existing declarations and inferred links
must remain distinguishable. No relationship count is a quality target: when
no useful supported relation is found, explain that outcome or the missing
input instead of silently implying that a tree is the complete explanation.
Changes to serialized relation kinds or meanings require a versioned migration
for schemas, saved claims, companion sheets and tracking/publication receipts.

## Optional navigation helpers and trusted operations

Language parsers and format readers may add symbol locations, call/reference
hints and configuration structure. Their output stays bounded source-derived
data. Missing helpers or unsupported syntax must fall back to supplied text
and source ranges, with limits disclosed. A new language must not require a
new semantic reviewer or a per-repository prompt.

Operator policy controls accessible repositories, authors, formats, budgets,
models and delivery modes. Transport adapters own GitHub-specific revision,
permission and merge-gate checks. Those security controls remain in force while
hardcoded pilot repository identities move toward operator configuration.
This plan does not expand any live access or publication grant.

## Delivery sequence

| Stage | Change | Reviewable outcome |
| --- | --- | --- |
| G1 — Common contract | Generalize the reviewer profile and relationship semantics; document compatibility and explicit empty-relation outcomes | One vocabulary supports responsibilities and relationships without requiring policy-library concepts |
| G2 — Evidence selection | Prefer relevant existing Hypercode, architecture documents/specifications and connecting configuration under a finite, configurable format policy | Hunter's missed inputs illustrate a generic selection rule; no repository-specific path branch is added |
| G3 — Bounded replay | Replay pinned examples with the same core profile, source limits and provider settings; inspect omissions and useful explanations | The operator can say `ok` or `not_ok` and inspect source support; optional parser hints can improve navigation later |

Use Hunter #22 and SpecGraph #773 as initial worked examples, with a
no-Hypercode example to check the fallback. Neither repository is an
acceptance template. Scientific comparison, new scores and extra merge-blocking
checks are not required for this increment. Keep earlier bundles immutable and
publish only through the existing authorized revision/tracking gate.
