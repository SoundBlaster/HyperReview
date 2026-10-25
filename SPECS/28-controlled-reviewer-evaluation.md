# Controlled reviewer evaluation

Use MLflow GenAI evaluation for comparing reviewer revisions and Evidently for
the local baseline/current report. This is separate from the earlier synthetic
boundary pilot. Neither evaluation is a publication gate.

## Freeze before changing behavior

The versioned [review suite](../evaluations/reviewer-v4.json) pins real PR
revisions, narrow deterministic witnesses and a short local human rubric. Keep
baseline artifacts and their digests before editing a prompt, selector or
renderer. Commit changes to criteria separately from the change being assessed;
do not rewrite expectations to make a candidate green. Keep unsuccessful
attempts and incomplete comparisons visible.

| Axis | Fixed | Variable |
| --- | --- | --- |
| `explanation` | Exact request inputs, including source bytes/order, evidence, selection, model, effort, executable and compiler | Reviewer profile/prompt and implementation |
| `intake` | Repository/base/head, prompt/profile and file/byte selection budgets | Retained evidence/source records |
| `model` | Identical complete request/profile, provider, effort, executable, reviewer runtime, schema/instruction seals, compiler and configured time budget | Model identity |

The [review-derived corpus](29-review-corpus.md) preserves observation packets,
separates model/validator cases and exports curated suites. Model-only pairs
require new receipts with matching runtime/budget seals; missing historical
seals remain unavailable, not inferred. No stronger model is invoked by the
comparator or native SDK adapter.

An explanation comparison rejects any input change outside the profile, prompt
version and resulting request digest. An intake comparison does not require
model output or compiler artifacts. For a selector experiment, collect from a
single saved API-response set and replay both collectors offline; identical
revision names alone do not freeze changing PR metadata or check observations.
The comparator validates identities and budgets, not the origin of that cache.
Keep its digest and collection receipt locally. Do not interpret a combined
intake/prompt change as a prompt-only improvement.

Use the existing private `prepare`, `generate` and `compile` workflow on each
revision. For an explanation-only replay, preserve the previous request fields
and sources, rebind only its current packaged profile/prompt and recompute the
request digest; current contract validation must still pass. Never edit the
baseline in place. Failed generation/compilation produces no eligible projection
pair: keep its local failure receipt and report the incomplete comparison.

## What is measured

The application extracts bounded, deterministic observations from sealed local
bundles; native `mlflow.genai.evaluate` scores these pre-generated outputs with
custom code scorers. No `predict_fn`, model judge or inference runs in evaluation.

| Witness | Establishes | Does not establish |
| --- | --- | --- |
| `source_retention` | Named same-side source was supplied | Source was understood |
| `relation_presence` | A selected kind and endpoint tokens (`relation`) or exact curated endpoint alternatives (`relation_exact`) occur in a same-side structured relation | Correct binding, meaning, execution or completeness |
| `forbidden_relation_absent` | A curated, source-reviewed incorrect relation is absent | Other relations are correct, or necessary relations are present |
| `containment_preserved` | The positive unambiguous literal role path is retained | Entire projection matches architecture |
| `compiler_receipt_consistent` | Stored projection/IR hashes agree with a successful compiler receipt | Fresh compilation, authenticity or behavioral correctness |

Relation checks deliberately avoid exact prose/node-name golden outputs, but
remain representation-sensitive witnesses. A review may explain a mechanism
well without selecting a particular edge. Missing measurements stay null and
are excluded from means; measured and unpaired case counts remain visible.
There is no combined quality score or statistical significance claim.

V3 adds a negative caller-attribution witness for SessionMonitor #143, paired
with the existing positive witnesses. Reporting no relations satisfies absence
but loses positive coverage. The metric definition advances to
`review-witnesses-v2`; previous suite versions, results and fingerprints stay
unchanged. This checks the known outer-component error, not arbitrary semantic
precision or every possible incorrect caller name.

V4 retains the three cases and adds SessionMonitor #145 at its reviewed base/head.
It pairs exact positive endpoints with a negative witness for a fabricated direct
`SessionMonitor.agentStatus -> UsageStore.snapshot` call. The supplied caller
invokes unqualified `snapshot(query:)`; its wrapper definition is not supplied.
The exact alternatives accept that literal target, `self.snapshot` or the
enclosing-type spelling, but not a compound target containing both calls. This
advances the metric definition to `review-witnesses-v3`; old suite files and
published results are unchanged. Exact witnesses are intentionally sensitive
to endpoint spelling and selected edges. They cannot prove arbitrary binding;
an absent selected edge is a coverage observation, not a semantic verdict.

Profile v17 / composition-v23 explicitly preserves unresolved receivers and
explains reduced input through its selection invariant, retained metadata and
fallback. It checks visible registration before declaring wiring unavailable.
The local converter rejects obvious lists in either `source_analysis calls`
endpoint and requests one bounded repair with `call_endpoint_list`. This is a
format check outside argument/generic/quoted regions, not a call resolver or
new evaluation/publication gate. Other relationship kinds may legitimately
describe several application sites; historical legacy plans remain readable.
An additional `literal_caller` repair detects only a narrow Swift lexical
contradiction: a bare literal target (or its `.init` spelling) has indexed
invocations, the claimed qualified caller is an exactly indexed named scope
in one cited file, and none of those invocations is in that scope. It declines
qualified member targets, aliases/constructor references, shorthand `.init`,
masked occurrences, non-declaration target mentions outside the indexed
`name(...)` form (including trailing closures, explicit generics and callable
references), ambiguous duplicate callers, incomplete/unsupported input
and saturated indexes. Other formats continue without this guard. It does not
resolve aliases, types, reachability or behavior, and passing it is not semantic
approval. Optional hints themselves remain untrusted navigation data.
The #145 rubric separately asks whether the explanation covers timestamp ties,
reset witnesses and full coverage rather than an arbitrary row limit. No
keyword score substitutes for reading that mechanism or the omission caveats.
Bounded comparison/callsite navigation follows the full source request, so the
small index remains close to the output decision. It stays in an untrusted
data block/user message, outside the trusted reviewer profile. Codex ends with
a short trusted call audit; no source-derived text is promoted into it. The
source records, optional 6144-byte navigation budget and context limits stay
unchanged. The packaged v17 profile is 16216 bytes.

Profile v16 / composition-v22 distinguishes architecture ownership from the
named operation containing a call. Optional `callsite_hints` provide up to four
literal targets and four distinct named caller/source locations per target,
inside the existing 6144-byte shared navigation budget. Added-file stems only
choose literal search words; they do not establish which file implements a
target. Python AST and a conservative Swift lexical adapter supply locations.
Swift skips comments/string contents, unsupported raw/triple strings,
conditional-compilation files, unbalanced braces and offset windows. Python
omits unnamed callbacks. Swift reports lexical named owners, including calls
inside closures; it does not resolve callback execution identity. Some
declaration forms are outside this partial index. Other
formats continue through the normal source-review path without this helper.
These are untrusted navigation hints, not resolved binding, a runtime call
graph or a new rejection/publication gate. Verify each hint in the source.

The existing local `feedback` command remains the human acceptance path:
`ok`/`not_ok` for the exact preview, with an optional note. Rubrics are reading
aids, not a new user study. Native evaluation always leaves semantic assessment
`pending`; deterministic scores cannot approve a review on the user's behalf.

## Local invocation

Use the existing optional evaluation runtime, pinned to MLflow 3.16.1 and
Evidently 0.7.23 (`requirements-evaluation-tracking.txt`). No worker dependency
or production configuration changes are required. Run the trusted command
outside analyzed checkouts, with the installed package or a trusted `PYTHONPATH`.

The private pair manifest has this shape (one entry per case/axis):

```json
{
  "schema": "hyperreview.review-pairs.v1",
  "suite_digest": "SHA256_OF_CANONICAL_SUITE",
  "pairs": [{
    "case_id": "case-001",
    "axis": "explanation",
    "baseline": "/absolute/private/baseline-bundle",
    "candidate": "/absolute/private/candidate-bundle",
    "baseline_digest": "SEALED_BASELINE_BUNDLE_DIGEST",
    "candidate_digest": "SEALED_CANDIDATE_BUNDLE_DIGEST"
  }]
}
```

Calculate suite fingerprints with `intake.digest(suite)` and artifact seals with
`review_evaluation.bundle_digest(path, axis="explanation")` (or `"intake"`).
The seal covers parsed request/evidence and, for explanations, result and
receipts. Projection and IR bytes must match their receipt bindings. These are
local integrity checks, not signatures or attestations.

```sh
~/.local/share/hyperreview/evaluation-runtime/bin/python -m hyperreview.review_evaluation_sdk \
  --suite /absolute/trusted/evaluations/reviewer-v4.json \
  --pairs /absolute/private/pairs.json \
  --database /absolute/private/evaluation/tracking.sqlite \
  --artifacts-root /absolute/private/evaluation/artifacts \
  --output-root /absolute/private/evaluation/reports
```

Use absolute non-symlink paths and private output/artifact directories. Each
explicit invocation creates new native runs, one per axis/variant, plus an
Evidently reference/current report per axis. Only fixed numeric fields, generic
case/check IDs and fingerprints reach the SDKs. Repository paths, code, prompts,
review text, local rubric and free-text feedback do not. Tracking is local
SQLite with an explicitly matched local artifact root; telemetry is disabled.
Generated report artifacts and native metrics are read back before delivery is
marked confirmed. A failed command may leave pending/failed local runs; there
is no automatic retry, outbox, CI model call or production/publishing side effect.

## Regression workflow

1. Freeze cases, baseline artifacts and settings; run candidate generation once
   per selected case and retain bounded repair attempts.
2. Run native evaluation; inspect per-check differences and unpaired cases.
3. Read the short Hypercode previews. Record `ok`/`not_ok` through existing
   feedback when making a human acceptance decision.
4. Keep failures alongside successful iterations. Add future regression cases
   before the next fix, and do not tune repeatedly against only one PR.

### Label audit

The initial v1 suite and its local results are retained. Source inspection found
that its quota witness named `QuotaPresentationSection`, although the immediate
`DesignNumericRow` construction is inside `QuotaCoverageSummary` (same file,
lines 125–136). V2 corrects that caller; it changes no model output. Re-score
the same sealed bundles under a new suite digest, never overwrite v1 scores.
This is a label correction discovered during development, not independent
confirmation of the candidate. Witness absence still does not prove incorrect
architecture: the six-row projection may select other legitimate connections.
5. Ship through normal code review and offline CI. Evidence supports the
   architecture explanation; it does not block its publication.
