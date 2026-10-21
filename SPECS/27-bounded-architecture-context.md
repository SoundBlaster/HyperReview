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

Profile v7 / prompt `composition-v13` distinguishes a changed obligation,
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

An unchanged `.hc` composition can accompany a changed `.hcs`. Compact render
v11 shows the property diff, excluding source/evidence comments so changed
revision labels do not masquerade as semantic changes. Full companion sheets
remain available. An added after-side relation without a before-side relation
means newly recorded by this review, not independently proven newly implemented.

The compact public comment contains a shared scope caveat and specific model
limitations. Operational/security prompt instructions remain in the full local
ledger. Literal declaration and Python syntax anchors can narrow citations;
these are navigation aids with whole-record fallback, not semantic verification.

## Delivery and remaining work

This layer follows #41 -> #42. It does not activate runtime code, change service
grants, rerun inference or rewrite published comments. Existing bundles remain
immutable; sanitized prompt-v11/v12 tracking events remain replayable. Old requests
are not silently upgraded to the new profile.

G3 prepares fresh pinned examples, including SpecGraph #777/#778, to inspect
whether changed bindings and constraints are useful in `.hcs`. Ordinary
`ok`/`not_ok` feedback is sufficient. Matching saved outputs is not an acceptance
criterion, and no new repository blocking gate is introduced.
