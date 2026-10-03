# HyperReview specifications

These documents define the proposed MVP contract. Requirements using MUST,
MUST NOT, and SHOULD describe intended implementation obligations; they do not
assert that enforcement already exists. Changes to these obligations need a
reviewable specification diff.

| Document | Requirement namespace | Responsibility |
|---|---|---|
| [Product](01-product.md) | HR-PROD | Scope and useful reviewer output |
| [Architecture](02-architecture.md) | HR-ARCH | Composition, ownership, provider boundary |
| [Contracts](03-contracts.md) | HR-DATA | Evidence, identities, job lifecycle, publication |
| [Security](04-security.md) | HR-SEC | Trust, eligibility, isolation, credentials |
| [Verification](05-verification.md) | HR-VERIFY | Acceptance scenarios and evaluation |
| [MLflow](06-mlflow.md) | HR-TRACK | Experiments, spans, assessments, and data minimization |
| [Evidently](07-evidently.md) | HR-EVAL | Comparable cases, quality reports, regression semantics |

The `.hc` model names architecture responsibilities with explicit IDs.
[SPECS/02-architecture.md](02-architecture.md) maps those IDs to requirements.
Markdown specifications supply behavioral semantics; `.hcs` supplies values and
property contracts. Neither node names nor property values enforce runtime
behavior by themselves.

The implementation language and exact model are open choices. These documents
are plain Markdown specifications, not a SpecPM package or registered SpecGraph
nodes. Future tooling integration must preserve their IDs and status.
