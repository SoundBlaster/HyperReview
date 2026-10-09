# Local metadata tracking and recovery

The first profile uses MLflow `3.16.1` with a direct, operator-selected SQLite
tracking URI. A loopback-only UI server reads the same database. The delivery
worker runs in a separate pinned virtual environment with a minimal environment;
it receives only a strictly allowlisted sanitized event. It does not receive
the source-bearing result bundle. No HTTP tracking client, provider autologging,
source artifacts, prompts, response bodies, claim text, or preview text are used.

## Identity and privacy

Each compiled preview already contains a local tracking correlation ID. An event
binds that ID and attempt to repository/PR, pinned revisions, input/output
digests, prompt and abstraction profile versions, compiler identity, counts, and
available metrics. The generation receipt separately binds the exact reviewer
profile; the request digest links it to the sanitized tracking event without
changing the durable outbox metadata shape.
The model identifier is fingerprinted rather than exported verbatim. Missing
counts and missing historical timing remain unavailable, not zero.

Before constructing an event, HyperReview rechecks evidence/request/result and
receipt bindings, `.hc` contents, IR/diff fingerprints, and preview availability.
The same event cannot silently acquire new content. Pending `tracking-event.v1`
records from `composition-v7` remain replayable after the prompt upgrade.
Neither these local integrity checks nor MLflow delivery certify the model's
interpretation.

The fixed experiment is `HyperReview manual preview v1`. Its artifact location
must exactly equal the trusted local root. The helper sets the exact SQLite URI
before constructing the client or tracer and rejects another installed MLflow
version. SDK plugins and packages remain part of the operator's trusted runtime;
an isolated environment is not a sandbox attestation.

## Manual trace semantics

The root trace is `hyperreview.preview.receipt_export`. Its controlled children
are collection, inference, projection validation, and rendering. Their inputs
and outputs are absent. They describe retrospective export of workflow receipts,
not analyzed PR execution. Existing elapsed metrics are recorded as attributes;
export-time spans do not pretend to reproduce historical stage timestamps.
Publication has not executed and is not represented by a completed span.

## Outbox and reconciliation

The metadata-only outbox persists an event before delivery. Events and receipts
are bounded to 64 KiB, with at most 100 pending events. The spool is bound to one
database/artifact-root/version fingerprint. A file lock serializes reconciliation;
conflicting identities, destinations, or receipts stop rather than overwrite.
The child invocation has a total timeout and bounded combined output.

The SDK searches all result pages for the same correlation and attempt before
creating a run or trace. It adopts a single compatible result after a lost
reply. Duplicate matches, changed metadata, metric conflicts, and incomplete
traces remain pending for operator attention. A completed `OK` trace must have
the expected run link, digest, and exact stage span names before confirmation.
Metric history is read before logging and verified afterward; replay does not
append duplicate values.

Confirmation persists experiment/run/trace IDs in a durable operational receipt
before removing the event. Source-bearing preview metadata is then reconciled
and its status becomes `ready`. Receipt retention is independent of preview
retention. A failure keeps the event pending and does not rerun inference.
`track --reconcile` handles one pending event per invocation; running `track
--bundle ...` afterward also reconciles that bundle's status and refreshes both
`preview.md` and `preview-compact.md` after tracking confirmation. Both output
paths are checked before replacement; writes remain individually atomic, not a
multi-file transaction. A refresh failure reports confirmed delivery with an
incomplete preview refresh, and replay can refresh without another inference.
No worker queue, automatic cleanup, failed-inference journal, or publication
authority is implemented by this increment. Spool capacity gates enqueueing;
integrating that gate before every analysis is a later one-shot/worker concern.

## Local setup

Install the pinned optional dependency in an isolated environment. Keep its
database, artifacts and operational receipts outside analyzed checkouts. For
this Mac, the runtime is `~/.local/share/hyperreview/runtime`, the database is
`~/.local/share/hyperreview/mlflow/tracking.db`, and the UI uses `127.0.0.1:5050`
because port 5000 is already occupied by macOS Control Center. No macOS service
was changed or permanent launch agent installed.

SDK writes go directly to SQLite, avoiding HTTP routing, redirects and proxy
configuration. The UI server is bound to loopback with restricted allowed hosts
and CORS origin. SQLite remains a shared database between UI and worker;
concurrent external writes are not protected by HyperReview's outbox lock and
must be excluded operationally. A busy database produces pending delivery.

## Evidence and limits

Offline fixtures cover event privacy, outbox order and replay, conflicting
destinations, tagged SDK recovery, incomplete traces, and artifact location.
The real preview of the selected SpecGraph PR #761 slice was delivered to local
MLflow, with one run, one root plus four child spans, and 12 numeric metrics.
Independent readback confirmed absent inputs/outputs and one history entry per
metric after a repeated `track` invocation. This establishes delivery and replay
for that local case, not crash-proof exactly-once semantics under arbitrary
external writers or future MLflow versions.

## Official references

- [Pinned MLflow client API](https://github.com/mlflow/mlflow/blob/v3.16.1/mlflow/tracking/client.py).
- [Tracking server and SQLite deployment](https://mlflow.org/docs/latest/self-hosting/architecture/tracking-server/).
- [MLflow license](https://github.com/mlflow/mlflow/blob/v3.16.1/LICENSE.txt).
