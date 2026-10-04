# Desired architecture of HyperReview

[reviewer.hc](reviewer.hc) describes the proposed reviewer's responsibilities.
[reviewer.hcs](reviewer.hcs) resolves its proposed operating values. This is an
architecture source for HyperReview itself, not an example of extracted PR
architecture or a configuration loader already implemented by this project.

Stable IDs map to obligations in [the architecture specification](../SPECS/02-architecture.md).
The tree expresses composition. Ordering of siblings is not execution order;
node names such as `PublicationGate` do not enforce authorization.

## Resolve a design profile

With the external Hypercode CLI available:

```sh
hypercode validate architecture/reviewer.hc --hcs architecture/reviewer.hcs
hypercode resolve architecture/reviewer.hc --hcs architecture/reviewer.hcs --ctx backend=lmstudio
hypercode emit architecture/reviewer.hc --hcs architecture/reviewer.hcs --ctx backend=ollama --ir-version 2
hypercode explain architecture/reviewer.hc --hcs architecture/reviewer.hcs --ctx backend=codex '#backend' provider
```

`backend=codex|lmstudio|ollama` selects the proposed provider settings. With no
backend context, provider configuration remains unavailable. A configured design
profile still requires operator model selection and runtime capability checks.
`mode=publish` requests delivery only; the trusted broker must separately verify
authorization, eligibility, valid artifacts, and fresh revisions. Local preview
remains available when publication is requested.

System context changes resolved values. Property contracts remain globally
applicable by selector matching. Current Hypercode contracts check primitive
types and numeric bounds; they do not enforce string enums, require a boolean to
be true/false, prohibit shell execution, isolate credentials, or validate the
truth of a source interpretation. Those semantics belong to HyperReview's
policy validator and runtime, as specified in [security](../SPECS/04-security.md).

The `.hcs` file is an illustrative trusted baseline; loading it as production
configuration is a future adapter decision. A PR MUST NOT be able to substitute
this baseline or any model instructions.

## MLflow responsibility

`#tracking` and `#mlflow` describe the selected local experiment backend.
`#traces` captures the reviewer workflow; it is not a trace of PR program
execution. `#evaluation` holds versioned technical cases and scorers; `#feedback` records
local `ok`/`not_ok` preview assessments independently of comparative research.
`#tracking-spool` recovers sanitized tracking delivery. Metadata-only capture
and disabled LLM judging are the initial policy; MLflow does not own job leases
or GitHub publication authority. See [the MLflow contract](../SPECS/06-mlflow.md).
No MLflow server is started by resolving this model.

`#reports` and `#evidently` produce local evaluation reports over shared
assessment data; `#baseline` and `#regression` define comparable cases and
operator-reviewed comparison policy. Report-only operation is the initial
profile. See [the Evidently contract](../SPECS/07-evidently.md).

## Artifact boundary

For analyzed PRs, HyperReview will emit separate `before.hc`/`after.hc` files,
identity/evidence records, and IR snapshots. `hypercode diff` compares resolved
content of those snapshots. Its success establishes a well-formed comparison,
not the correctness or completeness of inferred architecture.
