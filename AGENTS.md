# SpecificationCore coding guidance

When writing or reviewing HyperReview code that uses SpycificationCore's
`specification-core` Python package:

- Consult the available `specificationcore:specificationcore` skill for API
  guidance and `specificationcore:specification-patterns` when deciding whether
  a branch expresses a domain policy worth modeling as a Specification.
- This repository consumes the Python port. Check the exact commit pinned in
  `pyproject.toml` and use that version's Python source, documentation and tests
  as the API source of truth. Do not copy Swift-only APIs or change the pin as
  part of an application change unless requested.
- Model stable domain decisions with a small named rule and typed/frozen context.
  Keep parsing, GitHub access, orchestration and side effects in their owning
  layers; do not turn every `if` statement into a Specification.
- Preserve existing outcomes, ordering and error behavior. Test relevant
  branches, boundaries and no-match cases with local deterministic inputs. If
  tracing is used, keep trace names stable and omit source content, credentials
  and other PR metadata.

If these skills are unavailable, follow the pinned Python package API and the
behavior-preserving policy boundaries above.

# Review-derived evaluation corpus

- When handling a reviewer-quality finding, preserve its pinned preview with
  `python -m hyperreview.review_corpus capture` before changing the reviewer.
  Keep the input bytes, generated plan/result, receipts and feedback snapshot.
- New captures are candidates. Add source-checked criteria and provenance in a
  new version of the corpus manifest; a model comment is not human approval.
  Preserve useful positive examples alongside failures. Record omitted raw
  attempts as unavailable, never reconstruct them from a repaired result.
- Separate `model_review` cases from reviewer `validator` bugs. Keep every
  revision of one PR in one split. Cases used during development are not blind
  holdout; do not tune on a holdout without retiring its holdout designation.
- For a model-only comparison use axis `model`, with identical frozen requests,
  prompt/profile, effort, executable, compiler, reviewer runtime and configured
  time budget. Do not turn missing historical seals into invented lineage.
- Corpus capture and deterministic evaluation authorize no new inference,
  GitHub publication, model judge, worker configuration or production gate.
