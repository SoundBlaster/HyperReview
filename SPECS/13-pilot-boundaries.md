# Controlled pilot boundary reports

This increment prepares six synthetic technical cases and a local Evidently
report. It covers engineering boundaries; it is not user-feedback capture or a
scientific reviewer experiment.

## Dataset and execution

`controlled-boundaries-v1` contains a responsibility addition, unsupported core
syntax, an identity mismatch, an unsupported before baseline, a type rename with
stable architectural identity, and an approval bypass with unchanged composition.
The dataset digest binds sources, hand-authored projections, questions, expected
outcomes, and answer keys. Synthetic revision IDs are fixture inputs, not GitHub
evidence. No source is executed, and no model is called.

Each case uses the same pinned external compiler boundary as manual previews.
A rejection only passes when its controlled failure matches the expected
operation and diagnostic. The unsupported arrow case requires the parse
operation, exit status 1, and allowlisted diagnostic code `HC1001`; generic
compiler failures do not pass it. Compiler diagnostic messages and paths are
not retained in the assessment bundle.
Equal structure does not establish equal behavior: the approval-bypass case is
accepted structurally and requires source inspection to identify the violation.

Outputs include a reviewer worksheet, a separate answer key, and an unfilled
scorecard. They support inspection of the fixed fixtures, not a required study.
The intended P2 product feedback is one user's `ok` or `not_ok` assessment of a
preview on their own PR, with an optional note tied to the exact base/head
revisions and projection version shown. This feedback-capture path is not
implemented. Optional accuracy or review-time research is separate from the
product loop and is not a release, scheduler, or publication gate.

## Reporting subset

`hyperreview.evaluation.v1` accepts 5–10 unique fixed-format case IDs with
numeric or explicitly missing metric values. Unknown columns, prose, booleans
used as numbers, nonfinite values, and duplicate JSON fields are rejected.
Grammar and reference validity may be missing when the corresponding check did
not run; a successful compile records both as valid even if the observed
structural change count differs from the fixture expectation. Missing metric
values remain missing, and the summary reports measured-record coverage for
each metric. The metric definition is `boundary-v2`; these values describe
controlled validator outcomes, not general model quality.

Evidently `0.7.23` computes fixed technical metric means and exports JSON/HTML
locally. Case IDs and source data are excluded from the SDK table. Both
telemetry flags are set before SDK import. No Cloud, embeddings, or LLM judge is
configured.
The input is bounded to 64 KiB and each report artifact to 16 MiB. Private output
bundles contain the sanitized assessments, report, and a dataset-bound summary.
They do not measure user acceptance, human accuracy, review time, or model
superiority.

The optional report environment uses Python 3.12+ and SciPy `1.18.1`, separately
from the Python 3.10+ core CLI and MLflow runtime. Dependency versions do not
constitute a complete transitive lock. Reports are report-only; no regression or
publication gate is enabled. MLflow evaluation-run artifact handoff is
implemented; own-PR feedback capture remains unimplemented. Baseline comparisons
and accuracy/review-time studies are optional research.
