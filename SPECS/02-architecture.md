# Architecture specification

The structure in [reviewer.hc](../architecture/reviewer.hc) is the desired
composition of HyperReview itself. It is distinct from the illustrative
projections HyperReview will create for analyzed PRs.

## Responsibility mapping

| Stable ID | Responsibility | Primary obligations |
|---|---|---|
| `#worker` | Coordinate a bounded analysis job | HR-DATA-004, HR-SEC-007 |
| `#scheduler` | Poll configured repositories and resume after wake | HR-ARCH-003 |
| `#queue` | Serialize work and deduplicate job identities | HR-DATA-004 |
| `#journal` | Persist recoverable job transitions | HR-DATA-004 |
| `#github` | Read PR metadata and pinned source | HR-DATA-001, HR-SEC-001 |
| `#repositories` | Hold operator-owned repository allowlist | HR-SEC-001 |
| `#eligibility` | Reject non-eligible PRs before model access | HR-SEC-001 |
| `#snapshot` | Pin base, merge base, and head revisions | HR-DATA-001 |
| `#evidence` | Build a bounded evidence pack | HR-DATA-001, HR-SEC-002 |
| `#modelgateway` / `#backend` | Supply provider-neutral analysis | HR-ARCH-002, HR-SEC-003 |
| `#projection` / `#identities` | Produce paired composition and stable mappings | HR-DATA-002 |
| `#claims` | Track claim scope and supporting evidence | HR-DATA-003 |
| `#hypercode-validator` | Parse, validate, emit, and diff projections | HR-ARCH-001 |
| `#provenance` / `#scope` | Check references and coverage disclosures | HR-DATA-003 |
| `#artifacts` | Assemble a reproducible analysis result | HR-DATA-005 |
| `#renderer` / `#preview` | Render a local explanatory comment | HR-PROD-004 |
| `#publication-gate` | Recheck operator authorization and PR state | HR-SEC-005 |
| `#publisher` | Maintain the tool's ordinary PR comment | HR-DATA-006 |
| `#tracking` / `#mlflow` / `#traces` | Record MLflow runs and sanitized workflow spans | HR-TRACK-001, HR-TRACK-002, HR-TRACK-003 |
| `#evaluation` / `#cases` / `#scorers` / `#feedback` | Run technical fixture assessments and record local preview usefulness | HR-TRACK-004, HR-TRACK-005 |
| `#reports` / `#evidently` | Produce local quality reports and sanitized MLflow artifacts | HR-EVAL-002, HR-EVAL-004, HR-EVAL-005 |
| `#baseline` / `#regression` | Compare matched cases using reviewed metric definitions | HR-EVAL-001, HR-EVAL-003 |
| `#tracking-spool` | Recover bounded tracking delivery without repeat inference | HR-TRACK-006 |
| `#state` / `#audit` | Store deduplication state and redacted events | HR-DATA-004, HR-SEC-006 |
| `#budget` | Apply bounded resource use | HR-SEC-007 |
| `#credentials` / `#isolation` | Keep authority outside model-controlled work | HR-SEC-003, HR-SEC-004 |

## Ownership and invocation

**HR-ARCH-001 — Hypercode boundary.** HyperReview MUST consume the existing
Hypercode CLI/library and canonical IR; it MUST NOT extend core `.hc` with
`uses`, `emits`, `consumes`, arbitrary edges, or execution semantics. Rich source
relations may be stored in evidence outside the composition tree. A semantic IR
diff is deterministic for its inputs; it does not validate the model's source
interpretation. Provenance-only changes may require an additional claim/evidence
diff because `hypercode diff` compares resolved content.

**HR-ARCH-002 — Model adapters.** Codex CLI, LM Studio, and Ollama MUST implement
the same request/result contract. Provider, exact model, model revision when
available, prompt version, and isolation capabilities MUST be recorded. HTTP
adapters MUST use structured inference without executing model-requested tools.
Codex requires a separately verified restricted invocation profile before it
may run unattended. Unsupported isolation MUST disable that backend.

**HR-ARCH-003 — Local worker.** A future `launchd` service MUST invoke the same
bounded one-shot worker available manually. Polling defaults to 300 seconds;
only one job may run at once. Sleep may delay analysis; the worker MUST recover
on wake without claiming continuous availability. Installing the scheduler is
a separate operational step after the manual pilot passes acceptance.

**HR-ARCH-004 — Composition and contexts.** `.hc` names responsibilities, not
necessarily one class per node. `.hcs` selects provider and delivery values.
Contracts remain applicable by selector matching across contexts; context may
change whether resolved values satisfy those same contracts. Any boolean
policy invariant or enum semantics not expressible by current property
contracts MUST be enforced by HyperReview's trusted policy validator.
