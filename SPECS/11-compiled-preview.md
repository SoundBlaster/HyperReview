# Paired compilation and local explanation

This increment checks a proposed projection with an operator-selected external
Hypercode executable and renders a private Markdown review aid. All architectural
interpretations remain `inferred`; compiler acceptance is not architecture
conformance or a proof of implementation behavior.

## Compiler boundary

The operator supplies an absolute executable path and its SHA256. HyperReview
copies that binary from one no-follow file descriptor into a private directory,
verifies its fingerprint during and after copying, then launches that private
copy for every compiler command. The copy shares the preview deadline and is
capped at 128 MiB; replacing the original pathname after copying cannot select
a different program for execution. The current reference
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
generation receipt, persisted tracking correlation metadata, paired `.hc`,
paired IR, semantic diff, a compiler receipt, `preview.md`, and
`preview-compact.md`. The receipt binds request/result digests, compiler
fingerprint, and emitted artifacts. Its stage is `projections_validated`, not
the full pipeline's `ready` state: tracking and operational recovery remain
separate increments.

`preview.md` is the verbose diagnostic view. `preview-compact.md` is a concise
Russian review aid with a paired structural diff, per-node reasons, and
revision-specific source links. Both separate inferred model interpretations
from compiler-derived structure, escape prose, and keep the scope limitation
visible. When the paired trees are identical, the compact view says there is no
structural change and includes the current `.hc` tree so readers can see what
was compared. The compact view is for review and does not represent a publication
decision. Neither an unchanged tree nor a missing witness establishes unchanged
program behavior. `track --bundle` refreshes both files when tracking is
confirmed; `track --reconcile` alone only reconciles the outbox.

## Evidence

Offline fixtures exercise subprocess bounds, rejected compiler results, ID and
side provenance, artifact binding, and Markdown escaping. CI additionally runs
controlled paired-projection fixtures against its pinned compiled Hypercode.

The first real LM Studio proposal for a 440-byte added-file slice of SpecGraph
PR #761 passed the JSON contract but used an ID inconsistent with its `.hc` and
invented the same responsibility in the unsupported before projection. These
are validation failures, not acceptable architectural explanations. This case
motivates the boundary rather than demonstrating interpretation quality.

An earlier `composition-v2` analysis of the same pinned slice produced a newline-only before
projection and one after-side responsibility whose ID matched its source-backed
identity entry. That proposal passed the real compiler and rendered locally.
The success establishes this narrow pipeline path, not reviewer usefulness or
semantic correctness across the PR. The first failed proposal remains stored
separately and is not treated as a successful repair within its expired budget.

Prompt `composition-v3` now uses a
[structured composition plan](15-structured-composition.md) to derive IDs and
per-side provenance consistently. Older requests are rejected rather than
silently receiving a different prompt. This change has its own fixtures and
was exercised independently on four after-only source records from the historical
PR #761 head `06efdb7ea0de52610211a72183d5866491e8b104` (merge base
`ff1f89ea11eeeabaf003698d33cf56641a5aa101`). The PR has since been merged with a
different final head; this is a historical slice, not an analysis of that final
head. LM Studio gpt-oss-20b with explicit `developer` instructions, context
32768, and output limit 3072 generated one publication-policy root with three
children. The ordinary `generate` and `compile` commands accepted this result
without a manual rewrite. The trusted executable SHA256 was
`6503784100372b8fe93d0a794caf80bfbfc47da880874b2b9177267d34a26b9f`.
The earlier v2 result is not v3 evidence, and compiler acceptance does not
establish semantic accuracy. Earlier v3 attempts were rejected or produced
unhelpful inventories; this is a smoke result, not a reliability measurement.

Local own-PR feedback is now captured separately with exact revisions, projection
and preview fingerprints ([contract](16-preview-feedback.md)). Metadata-only
MLflow delivery is already implemented; controlled publishing remains next.
