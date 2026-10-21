# Bounded architecture context (G2)

## Selection contract

Intake policy `own-pr-intake.v4` uses the same rules across repositories. The
ordinary code/Markdown/`.hc` extension list remains finite. Additional untrusted
declarative text is admitted through reviewed semantic families:

- `.github/workflows/*.yml` and `*.yaml`;
- YAML under any `specs/` or `specifications/` directory, `*.spec.yaml/yml`, and
  `specpm.yaml/yml`;
- JSON files directly inside a directory whose name contains `decision`;
- `Cargo.toml`, `pyproject.toml`, and `package.json` manifests;
- `bindings.json/yaml/yml` and `*.bindings.json/yaml/yml`;
- `.hcs` companions; the previous feature-passport path family remains supported.

Arbitrary YAML/JSON, operator instructions and sensitive paths remain excluded.
Family admission is a text-selection convention, not schema validity, accepted
intent, approval or evidence that a declared check passed. Family changes require
reviewed code; operator configuration does not grant arbitrary file patterns.

Hypercode is selected before other declarative evidence, implementation, tests
and prose. Request normalization preserves that priority under a smaller model
source budget. Prose has an additional aggregate 87381-byte cap. All evidence
still shares the 262144-byte encoded-pack cap, 30 logical source files, 60 source
records, GitHub response/read deadlines, eligibility and revision checks.

## Unchanged context

The complete pinned trees also permit a bounded context selection:

1. Add same-basename `.hc`/`.hcs` companions of changed Hypercode files. Otherwise
   select one existing map and its companion, ranked by directory proximity to
   the first 30 changed paths, then depth/path. Fixtures, examples, dependencies
   and common generated directories are excluded from automatic map discovery.
   This heuristic chooses a candidate, not the repository's authoritative map.
2. From retained changed Markdown/Hypercode/declarative sources, follow one hop
   of literal repository-relative paths (including root-level files) that exist
   in that side's pinned tree.
   Do not follow URLs, imports, includes, commands or recursive references.
3. Share at most eight context files and 65536 content bytes across both sides
   within the ordinary total caps. Existing Hypercode counts toward this limit.
   Additional candidate paths are outside this bounded selection, not proof of
   absence. Every selected read/excerpt failure remains an omission.

Optional context inventory is admitted incrementally within the encoded cap.
Insufficient metadata room records `context_inventory_limit`; it cannot abort
an otherwise valid changed-source collection.

Context records are marked `status=context` with their selection reason in the
evidence pack. Their presence does not imply a source change. They receive the
same regular-blob, path and digest checks as changed sources. Ordinary context
blobs are checked for recognized secret patterns before windowing. Configuration
retains its full-blob filtering and original-blob/excerpt coverage ledger.

An ordinary context file is read only up to 65536 bytes. Remaining context bytes
are shared across remaining context files and their sides, preventing an early
large implementation file from starving later verification targets. When a file
cannot fit its allocation, retain one original-line window of at most 64 lines.
Prefer a literal symbol from added declarations, then other same-side references;
locate its textual definition when possible, otherwise its first occurrence or
the file start. These hints do not establish semantic binding. Record
`context_excerpted`; a missing definition or another use outside the window is
unknown. The window does not establish complete function or call-graph coverage.
Budget exhaustion and oversized files are explicit omissions. No PR code runs.

## Explanation contract

Profile v9 / prompt `composition-v15` distinguishes a changed obligation,
constraint or test binding from a changed implementation. `verified_by` is an
additive common relation kind for declared obligation-to-check links. It does
not imply execution, passing results or exhaustive coverage. Existing relation
IDs and meanings remain unchanged.

Request v5 carries an `unchanged_files` ledger derived from equal collector-verified
full Git blob identities, bound to the retained source IDs on both sides.
Different excerpt windows must not be described as new/changed implementation.
The paired #777 replay exposed this failure before any publication; a test
definition present in a larger after-window was incorrectly called newly added.
Absence of an unchanged marker does not prove a file changed. Full-blob identity
is about source bytes, not runtime behavior or external dependencies.

For `verified_by` declarations, `to` contains one complete verbatim target,
without concatenation or truncation. The whole target with identifier boundaries
must occur in the cited records on that side. Missing literal evidence
raises the safe `verified_binding_target` repair issue. This rejects the #777
pilot's unsupported before-side target, even though that function already
existed in implementation. It does not prove the owner-to-target relationship,
test coverage or execution; the guard is format/language independent and does
not interpret target syntax.

An unchanged `.hc` composition can accompany different selected `.hcs` properties.
Compact render v13 shows comment-free selected properties separately for each
revision, or once when both selections are identical. Empty selections have no
visible code block; their full sheets and unselected meaning remain in the
disclosure, never a claim that relationships are absent. Full compiler-bound
companion sheets remain available with evidence comments.

These bounded selections are not complete relationship inventories: the #778
replay selected two preserved bindings before and only the additional binding
after. Subtracting the selections incorrectly rendered the preserved bindings as
removed. The renderer therefore does not produce a `.hcs` unified diff or copy
missing claims between revisions. A source-change view would require a separate
paired comparison contract with evidence for presence/absence and analysis
coverage. Valid same-side targets alone cannot establish addition or removal.
The `.hc` containment diff retains its existing presentation semantics.

The first screen contains a short inferred-sketch label, the pinned head prefix,
the `.hc` composition/diff and selected `.hcs` properties. The Hypercode is the
primary explanation; do not truncate targets or manufacture a shorter summary.
One collapsed `details` section contains the full model summary, relationship
table, per-responsibility prose, citations, complete companion sheets, diff
legend, coverage and limitations. Identical selections are displayed once;
evidence and safety qualifications remain available without dominating the first
screen. The historical read-only/publication-disabled notice stays visible.
This is a presentation change; generation results and compiler receipts remain
bound and existing bundles are not silently rewritten.

Operational/security prompt instructions remain in the full local ledger.
Literal declaration and Python syntax anchors can narrow citations; these are
navigation aids with whole-record fallback, not semantic verification.

## Delivery and remaining work

This layer follows #41 -> #42. It does not activate runtime code, change service
grants, rerun inference or rewrite published comments. Existing bundles remain
immutable; sanitized prompt-v11/v12/v13 tracking events remain replayable. Old requests
are not silently upgraded to the new profile.

G3 prepares fresh pinned examples, including SpecGraph #777/#778, to inspect
whether changed bindings and constraints are useful in `.hcs`. Ordinary
`ok`/`not_ok` feedback is sufficient. Matching saved outputs is not an acceptance
criterion, and no new repository blocking gate is introduced.
