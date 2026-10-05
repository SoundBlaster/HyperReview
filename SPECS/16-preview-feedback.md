# Local preview feedback

`hyperreview feedback` captures one operator assessment of the compact preview:
`ok` or `not_ok`, plus an optional note. This describes whether the preview is
useful to the operator; it is not a behavioral proof, authenticated review, or
publication authorization.

## Binding the assessment

The command validates the compiled bundle's evidence, request, canonical result,
projection artifacts and compiler receipts. The compact Markdown must match the
current renderer for that result. Feedback records pin repository/PR, exact
merge-base/head revisions, request/result and paired-projection digests, compact
preview SHA256, prompt/abstraction/render versions, compiler fingerprint, and
local tracking correlation ID. They can be captured before tracking delivery;
feedback does not change delivery state.

By default the command assesses the current file. The optional
`--expected-preview-sha256` checks the fingerprint of the version actually shown,
and rejects a changed preview. A mismatched or tampered bundle produces no
feedback record. This path supports the current request/renderer contracts;
it does not migrate historical artifacts to a new rendering version.

## Local storage and privacy

Each submission creates a new private UUID bundle containing `feedback.json`;
prior assessments and analysis artifacts are not overwritten. Notes are limited
to 2000 characters and are not printed in diagnostics. Records stay local under
`~/.local/share/hyperreview/feedback/` by default (directory 0700, file 0600).

The command performs no inference, SDK delivery, evaluation export, GitHub API
request, or publication. Free-text notes do not enter MLflow/Evidently reports.
No quality threshold or comparative reviewer experiment is required. The record
is an operator assertion, without signatures or a check of who viewed it.
