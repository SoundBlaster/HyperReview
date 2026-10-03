# HyperReview

A local PR reviewer that explains architectural changes using illustrative
Hypercode projections, source references, and explicit evidence boundaries.

**Status: specification bootstrap.** This repository defines the pilot;
no worker, model adapter, scheduler, or GitHub publisher is implemented yet.
The Hypercode model describes the proposed reviewer, not an installed service.

## The pilot

For an eligible PR, collect pinned before/after source data, build a paired
architecture projection with stable IDs, validate the artifacts, and produce
one concise Markdown explanation with a Hypercode diff. Initial operation is
local preview. Publication is a separately enabled mode.

The initial repository allowlist is `0al-spec/SpecGraph` and
`0al-spec/Hypercode`, with PR author `SoundBlaster` and same-repository heads.
These are operator-owned settings, never instructions loaded from a PR.

## Specifications and architecture

- [Specification index](SPECS/README.md): requirements and acceptance criteria.
- [Product scope](SPECS/01-product.md).
- [Architecture and responsibilities](SPECS/02-architecture.md).
- [Data and lifecycle contracts](SPECS/03-contracts.md).
- [Trust and publication policy](SPECS/04-security.md).
- [Verification and pilot evaluation](SPECS/05-verification.md).
- [MLflow tracking and evaluation](SPECS/06-mlflow.md).
- [Evidently quality and regression reports](SPECS/07-evidently.md).
- [Hypercode model](architecture/README.md): readable `.hc` structure and
  context-resolved `.hcs` configuration.
- [Implementation workplan](workplan.md).

## Design principles

An illustrative projection is an interpretation of source evidence, not an
accepted architecture specification or proof of behavior. Hypercode is used for
composition, context resolution, provenance, and IR comparison. Scanning code,
interpreting responsibilities, checking evidence, and publishing belong to
HyperReview. Canonical expected architecture, when supplied, stays separate
from inferred projections.

MLflow is the selected system for experiment runs, manually instrumented traces,
and pilot evaluation. Its local deployment is specified but not installed.
Evidently produces local quality/regression reports from versioned assessments;
sanitized report artifacts and summaries are linked to MLflow evaluation runs.
Operational job/publication state remains in a separate store.

Model backends are interchangeable: Codex CLI, LM Studio HTTP API, and Ollama
HTTP API. Backend readiness and isolation must be verified before use; an
installed executable alone does not establish a safe unattended setup.

## License

[MIT](LICENSE). The license covers these specifications and examples as well as
future project code. Hypercode remains an external dependency with its own
[licenses](https://github.com/0al-spec/Hypercode#license).
