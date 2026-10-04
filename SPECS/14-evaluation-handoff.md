# Local evaluation artifact handoff

This subset links deterministic boundary assessments to an MLflow evaluation
run. It does not complete the human comparison or enable publication.

## Trusted export boundary

The input must pass the exact numeric-only `hyperreview.evaluation.v1` contract.
The application regenerates the Evidently report from that input before
delivery. It does not accept an arbitrary existing HTML/JSON file as sanitized
data. The upload consists only of application-selected assessment, summary,
and freshly generated report artifacts. Dataset and report fingerprints provide
lineage; exporting assessments to MLflow and Evidently does not create two
independent measurements.

The trusted SDK environment pins MLflow `3.16.1` and Evidently `0.7.23`. Operator
paths must be absolute and must not traverse symlinks or include `..` components.
SQLite database paths reject `?`, `#`, `%`, and control characters so URI parsing
cannot change the selected filename. Delivery uses a local
SQLite database and a local artifact root, with an evaluation experiment
separate from manual preview workflow runs. No inference or GitHub write occurs.
Run the optional command with a minimal environment outside analyzed checkouts.

## Recovery limits

Reports remain local if delivery fails. Repeating an explicit invocation
regenerates reports without invoking an analysis model, but may create another
evaluation run. This increment has no durable evaluation outbox or retry
idempotency; the manual-preview tracking outbox does not cover evaluation runs.
Do not use this export as a background retrying worker or a publication gate.

P2 still requires matched real cases, independent human answers and timing,
baseline/current comparison, coverage review, and operator-reviewed thresholds
before any quality gate is introduced.
