# Paired compilation and local explanation

This increment checks a proposed projection with an operator-selected external
Hypercode executable and renders a private Markdown review aid. All architectural
interpretations remain `inferred`; compiler acceptance is not architecture
conformance or a proof of implementation behavior.

## Compiler boundary

The operator supplies an absolute executable path and its SHA256. HyperReview
checks that fingerprint before and after compilation. The current reference
toolchain is Hypercode revision `7d23efdc9976226a21e1fc301730940d62097607`,
using IR v2 and diff v1. A binary fingerprint identifies the invoked executable;
it does not independently prove that binary's source revision. Build provenance
comes from the operator's trusted build or the pinned CI checkout.

The application writes fixed-name `.hc` inputs in a private temporary directory,
then invokes parse, validate, emit, and semantic diff commands. The model supplies
composition text only. No model-provided `.hcs`, imports, command arguments,
contexts, source checkouts, or executable code enter this invocation. Time and
output bytes are bounded; diagnostics do not replay source or compiler output.

Every node needs an explicit globally unique ID within each projection. The
union of compiled IDs must match the identity map exactly. A node present on
either side needs source references on that side; a reference cannot attach to
a node absent on that side. For a genuinely added or removed responsibility,
the opposite projection can be empty, expressed as a newline-only `.hc` file.
This checks the existence and revision of provenance, not semantic entailment.

## Local artifacts and rendering

The `compile` command also rebuilds the request from the supplied evidence pack
and original selection settings. Mismatched packs, modified requests, malformed
projections, dangling IDs, or unsupported side mappings fail without a preview.

Successful private bundles include evidence, request, proposed result, a bound
generation receipt, persisted tracking correlation metadata, paired
`.hc`, paired IR, semantic diff, a compiler receipt, and `preview.md`. The receipt
binds request/result digests, compiler fingerprint, and emitted artifacts. Its
stage is `projections_validated`, not the full pipeline's `ready` state: tracking
and operational recovery remain separate increments.

The preview separates model summaries/claims/identity decisions from
compiler-derived structural change records. Source links are built from
validated repository, revision, and path fields. Model prose is escaped and
projection fences adapt to embedded backticks. Omissions and limited analysis
scope remain visible. Neither an unchanged tree nor a missing witness establishes
unchanged program behavior.

## Evidence

Offline fixtures exercise subprocess bounds, rejected compiler results, ID and
side provenance, artifact binding, and Markdown escaping. CI additionally runs
controlled paired-projection fixtures against its pinned compiled Hypercode.

The first real LM Studio proposal for a 440-byte added-file slice of SpecGraph
PR #761 passed the JSON contract but used an ID inconsistent with its `.hc` and
invented the same responsibility in the unsupported before projection. These
are validation failures, not acceptable architectural explanations. This case
motivates the boundary rather than demonstrating interpretation quality.

Prompt `composition-v2` makes ID and per-side provenance instructions explicit;
older requests are rejected rather than silently receiving a different prompt.
A fresh analysis of the same pinned slice produced a newline-only before
projection and one after-side responsibility whose ID matched its source-backed
identity entry. That proposal passed the real compiler and rendered locally.
The success establishes this narrow pipeline path, not reviewer usefulness or
semantic correctness across the PR. The first failed proposal remains stored
separately and is not treated as a successful repair within its expired budget.

Next: sanitized local MLflow delivery, persisted correlation/recovery receipts,
and an end-to-end accepted preview with explicit inference limitations.
