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
