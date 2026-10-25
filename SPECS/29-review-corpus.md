# Review-derived model evaluation corpus

Luna is the current baseline and a useful source of counterexamples, not the
authority defining correct architecture. A stronger model must face the same
frozen inputs and criteria. This corpus measures selected review witnesses;
it is not a general intelligence benchmark or human approval mechanism.

## Preserve observations before fixing them

`review_corpus capture` copies a validated local preview into a private packet:
request/evidence bytes, result, projections/IR, compiler and generation receipts,
available final composition plan, compact review and feedback snapshot. Source
paths are not live dependencies after capture. Content seals detect mutation;
they are local integrity checks, not signatures or proof of the feedback's truth.
Capture is explicit and read-only with respect to GitHub and running workers.

Every capture starts as `candidate`, even if its feedback says to approve it.
Feedback text and its asserted human/agent/model source remain untrusted data.
Source-checked criteria are curated separately in a versioned manifest with a
rationale and assessor kind. No model comment can automatically promote itself
to a source-checked label; agent curation is visibly different from human
acceptance. The existing `ok`/`not_ok` workflow stays separate.

Use the existing suite case format for expected positive/negative relations,
containment, source retention and reading rubrics. Keep both failing and useful
outputs. Missing selected edges measure coverage, not necessarily false claims.
The importer preserves the available final provider plan, not all earlier raw
responses. `final_plan_only`/`unavailable` is explicit; repair receipts are not
reconstructed first-attempt content. Failed/uncompiled generations still need
their failure receipts retained separately and remain unpaired in comparisons.

## Keep different populations separate

The checked-in [v1 manifest](../evaluations/review-corpus-v1.json) contains four
model-review cases and a distinct validator group with three counterexamples
and controls. Seven model observation packets and one validator packet were
frozen privately. The #57 finding is a reviewer implementation bug, not evidence
that Luna misunderstood the reviewed product. Validator source strings are
parsed as data in offline tests; they are not executed or sent to models.

All five groups have already informed implementation and belong to
`development`. There is no blind holdout yet. Future holdout must be collected
before tuning; all revisions of one repository/PR stay in the same split.
The manifest rejects cross-split PR leakage and tuned holdout labels. These
operator declarations are not an automated audit of prior exposure. Candidate
or validator records do not enter a model suite.

## Operator workflow

Run from a trusted checkout/runtime, outside the analyzed repository. Paths
must be absolute, non-symlink and private where appropriate. No cloud call,
SDK upload, source execution or GitHub mutation happens in these commands.

```sh
python -m hyperreview.review_corpus capture \
  --bundle /private/path/to/preview \
  --suite /trusted/path/evaluations/reviewer-v4.json --case-id case-004 \
  --feedback /private/path/feedback.json --output-root /private/path/corpus
```

The feedback JSON has fields `schema=hyperreview.corpus-feedback.v1`,
`source=github_review|local_assessment`, `author_kind=human|agent|model`,
`url` (a GitHub PR/comment URL, or null for local assessment), and `body`.
It is an operator snapshot, not authenticated authorship. Add returned content
IDs to a new curated manifest version after checking the source. Duplicate
captures have the same content ID; no packet is overwritten.

```sh
python -m hyperreview.review_corpus capture-validator \
  --fixture /trusted/path/evaluations/fixtures/literal-caller-v1.json \
  --feedback /private/path/feedback.json --output-root /private/path/corpus

python -m hyperreview.review_corpus suite \
  --corpus /trusted/path/evaluations/review-corpus-v1.json \
  --records-root /private/path/corpus --split development
```

Suite export verifies packet seals and matching cases, requires actual local
records, and excludes feedback prose. At most 16 cases fit a suite; repeat
`--case-id case-001` etc. to select a bounded subset. A corpus shard holds up to
64 entries; the private registry scan is bounded at 512 packets. The capture
commands do not automatically curate a case, change the worker or run models.

## Compare models without changing the test

Use `axis=model` in the existing private pair manifest and native
[MLflow/Evidently workflow](28-controlled-reviewer-evaluation.md). Re-run Luna
and each candidate on the exact same prepared request under the current
trusted profile. Rebinding an old request to the current profile happens once
before both runs; preserve its source bytes and freeze the resulting request.
Never compare an old weak-model response with a stronger model on a fixed
prompt and call that a model-only improvement.

The model axis permits the model name/revision to vary, requiring identical:

- complete request, source bytes/order, profile and prompt;
- provider, effort and executable SHA;
- reviewer code/runtime and instruction/schema seals;
- compiler SHA and configured generation wall-clock budget.

New worker receipts bind the runtime before/after generation and record its
configured budget. Historical receipts without these seals remain usable for
other axes, but cannot be silently upgraded to model comparisons. Existing
`explanation` still requires fixed models; `intake` still fixes prompt/budgets.
Comparisons describe the same guarded review pipeline with a different model,
not isolated first-attempt reasoning. Report missing/unpaired cases and repair
history; do not rank only successful survivors.

Only numeric witnesses, opaque settings/code hashes and generic case IDs reach
the existing native SDKs. Model names/settings remain inspectable in the private
generation receipts. No source/feedback prose, model judge or new publication
gate is introduced. Stronger-model inference is a separate explicit run; this
increment does not invoke or select a new model.
