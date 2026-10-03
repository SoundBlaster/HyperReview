# Controlled pilot boundary reports

This increment prepares six synthetic cases and a local Evidently report. It
implements part of P2, not the human comparison required to complete P2.

## Dataset and execution

`controlled-boundaries-v1` contains a responsibility addition, unsupported core
syntax, an identity mismatch, an unsupported before baseline, a type rename with
stable architectural identity, and an approval bypass with unchanged composition.
The dataset digest binds sources, hand-authored projections, questions, expected
outcomes, and answer keys. Synthetic revision IDs are fixture inputs, not GitHub
evidence. No source is executed, and no model is called.

Each case uses the same pinned external compiler boundary as manual previews.
A rejection only passes when its controlled diagnostic matches the expected
failure; an unrelated compiler failure is not a successful negative test.
Equal structure does not establish equal behavior: the approval-bypass case is
accepted structurally and requires source inspection to identify the violation.

Outputs include a reviewer worksheet, a separate answer key, and an unfilled
scorecard. Human correctness, missed violations, confidence, and review time
remain unmeasured. These materials do not constitute the matched ordinary-PR,
LLM-explanation, and HyperReview study defined by the product specifications.

## Reporting subset

`hyperreview.evaluation.v1` accepts 5–10 unique fixed-format case IDs and numeric
boundary assessments only. Unknown columns, prose, booleans used as numbers,
nonfinite values, and duplicate JSON fields are rejected. Missing structural
change counts remain missing. The metric definition is `boundary-v1`; these
values describe controlled validator outcomes, not general model quality.

Evidently `0.7.23` computes fixed numeric means and exports JSON/HTML locally.
Case IDs and source data are excluded from the SDK table. Both telemetry flags
are set before SDK import. No Cloud, embeddings, or LLM judge is configured.
The input is bounded to 64 KiB and each report artifact to 16 MiB. Private output
bundles contain the sanitized assessments, report, and a dataset-bound summary.

The optional report environment uses Python 3.12+ and SciPy `1.18.1`, separately
from the Python 3.10+ core CLI and MLflow runtime. Dependency versions do not
constitute a complete transitive lock. Reports are report-only; no regression or
publication gate is enabled. MLflow evaluation-run artifact handoff, baseline
comparison, and human assessments remain subsequent work.
