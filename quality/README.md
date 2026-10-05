# HyperReview project quality observations

This is development tooling for the HyperReview source, outside the PR-analysis
worker. It does not send source to a hosted classifier or evaluate whether a
model explanation is correct. MLflow/Evidently and reviewer feedback retain
those separate responsibilities.

## Dependencies and scope

- Runtime: `specification-core` from SpycificationCore, pinned in `pyproject.toml`.
- Collector: SpecificationMetrics, pinned by repository/commit in `toolchain.json`.
- Python observations: Radon 6.0.1 and complexipy 8.0.1, pinned in
  `../requirements-quality.txt`; install only in a development environment.
- Scope: `hyperreview/` is application; `tests/` is test; `tools/` is excluded
  development plumbing. Unassigned supported files are diagnostics. Dependencies,
  `.toolchain/` and `.artifacts/` are ignored; dependency definitions are not
  credited as application Specifications. New application modules enter scope
  automatically.

The two user-owned dependencies are MIT. Radon and complexipy are also MIT;
retain their notices if distributing their tools. Version pins establish source
identity, not reproducible wheel/compiler hashes.

## Local setup and collection

Use Python 3.10+ and Rust 1.97.0 (the CI toolchain):

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e . -r requirements-quality.txt

git clone https://github.com/SoundBlaster/SpecificationMetrics.git .toolchain/specificationmetrics
git -C .toolchain/specificationmetrics checkout --detach db72934c533910be999382bf67cfb47a708d5d65
cargo build --release --locked --manifest-path .toolchain/specificationmetrics/Cargo.toml

.toolchain/specificationmetrics/target/release/specification-metrics collect \
  --config quality/collection.toml \
  --output .artifacts/quality/current.json \
  --store .artifacts/quality/history.sqlite
```

`collection.toml` paths are config-relative; `python3` must resolve to the
activated development environment containing the measurement packages. The
collector runs Radon/complexipy on captured source bytes without importing the
application. Duplicate-code collection is disabled, so its status is
`not_requested`, not zero. No hosted `classify` command is invoked.

## History and comparisons

Each local collection is recorded in SQLite with source revision/digest, scope
contract, counting rules, status and tool versions. Repeat the command after an
edit to retain a new observation; unchanged snapshots are idempotent.

```sh
.toolchain/specificationmetrics/target/release/specification-metrics collection-history \
  --store .artifacts/quality/history.sqlite --limit 20

# Save before.json and after.json from separate runs under the same contract.
.toolchain/specificationmetrics/target/release/specification-metrics compare \
  .artifacts/quality/before.json .artifacts/quality/after.json \
  --output .artifacts/quality/diff.json
```

A Git revision is provenance: local edits may differ from HEAD, so the captured
source digest remains necessary. CI artifacts retain each run's JSON and SQLite
for 14 days. Each job starts its own store; CI does not combine separate runs
into a shared database. Download compatible JSON artifacts for comparison.

## Interpretation

S/U measures adoption of Specifications among syntactically discovered decision
opportunities. It is neither a percentage nor a general code-quality score.
Do not convert every `if` to improve it: parsing, I/O and execution mechanics
remain in their owning layers. LOC, CC and Cog are separate observations;
lambda completeness and overall architecture quality are not established.

Liveness is conservative (`closed_world = false`): public/unresolved rules can
stay unknown, making the collection provisional. Preserve that status rather
than counting missing observations as zero. CI rejects parse/scope/marker
errors; it does not impose S/U, LOC, CC or Cog thresholds or require complete
liveness. Requested supplementary failures remain visible in report diagnostics.
