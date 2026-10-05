# SpecificationCore and project quality integration

## Policy dependency

**HR-QUALITY-001.** HyperReview uses the Python `specification-core` distribution
from SpycificationCore at the exact commit in `pyproject.toml`. Installation and
CI must resolve that dependency before intake. Keep the package's MIT notice.

**HR-QUALITY-002.** The initial extraction is one named pure
`PullRequestMetadataEligibility` Specification. Its frozen context supplies
requested PR/repository/author and the six metadata facts. The rule returns a
boolean; intake owns allowlist/account authority, revision syntax, exceptions
and subsequent GitHub reads. Preserve existing outcomes, false-identity handling,
error text and precedence. A local trace contains only rule name/outcome, not
raw PR metadata; tracing is not added to MLflow by this change.

This is a bounded application of the pattern, not a requirement to replace
mechanical `if` statements throughout the worker.

## Measurement dependency

**HR-QUALITY-003.** SpecificationMetrics is pinned in `quality/toolchain.json`
and built with `Cargo.lock`. It is development/CI tooling, not a Python runtime
package or a step that executes analyzed PR code. `quality/source-roles.toml`
assigns application, test and tooling ownership. Only application sources feed
both primary and supplementary observations. Collectors must retain source
revision/digest, scope and counting-rule versions.

**HR-QUALITY-004.** Collect application S/U plus Python LOC/CC/Cog using pinned
Radon/complexipy. Report each dimension and diagnostic independently. Missing
measurements must not become zero; unknown liveness remains provisional.
Do not synthesize an aggregate quality score or impose an adoption-ratio gate.
Syntax opportunities are inspection candidates, not mandatory conversions.

**HR-QUALITY-005.** Local SQLite records compatible source snapshots for history;
CI exports revision-bound JSON/SQLite artifacts. CI stores are separate per run,
with 14-day artifact retention. Parse, scope and marker issues fail the CI job;
provisional liveness and supplementary diagnostics stay visible without an
invented quality verdict. Compare snapshots only under a compatible contract.

## Boundaries

SpecificationMetrics observes HyperReview implementation structure. It does not
prove behavior, source privacy or explanation accuracy. Existing tests/compiler
checks, MLflow workflow observations, Evidently technical reports and the user's
`ok`/`not_ok` preview feedback retain their own meaning. No hosted classification,
new publication authority, code-generation adapter framework or automatic
policy rewrite is introduced.

See [local collection and comparison](../quality/README.md).
