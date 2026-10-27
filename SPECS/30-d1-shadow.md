# Local d1 shadow triage

This opt-in pilot collects an independent d1 observation for a completed private
preview. It does not judge the review, skip a PR, block or allow a merge, post a
comment, or update an existing worker's database. The repository owner retains
all review and merge decisions.

- The observer reads the production journal using SQLite `mode=ro`. It selects
  only completed preview jobs linked to retained, validated intake handoffs for
  the existing four-repository allowlist. It closes the read transaction before
  inference, and waits while preview work is queued or analyzing or intake is
  collecting. A job's preview identity and handoff are checked before and after
  the model call.
- A configured `not_before` timestamp prevents automatic processing of historic
  jobs. Explicit `--job` mode permits an operator to test a retained historical
  preview; its result is labeled `historical_probe`. Job IDs are claimed in a
  separate private journal before inference; failures and interruptions do not
  trigger automatic retries.
- At most two changed paths and their bounded before/after windows are sent to
  the model. When paired windows start on the same line, their diff is an excerpt
  diff, not a complete PR diff; otherwise the supplied windows are shown as
  excerpts. Coverage, omitted paths and the absence of a PR title are disclosed.
  The model sees untrusted source as data. Each output identifies the source
  references, request digest, reviewed head and preview digest; results go to a
  private directory beside, not inside, the signed preview bundle.
- The pinned d1 snapshot and model code are hash-checked. Inference is a
  lower-priority subprocess with a restricted environment and network denied by
  macOS sandbox; it runs on local MPS. It makes separate classification and
  multi-signal calls. An empty signal list is not a positive uncertainty signal.
  Predictions, including contradictory signals, are observations rather than
  calibrated decisions or proof about code.
- Each scheduled tick handles at most one job. The observer and reviewer remain
  separate processes and journals, although they share machine resources; a
  new review could start after the observer checks for an idle worker.
- Private JSON and Markdown results are bounded by the input selection and do
  not contain copied source excerpts. They are not automatically published or
  uploaded to MLflow. Logs and failure codes omit source text and error prose.
  The local journal retains at most 2048 receipts, after which processing stops
  pending operator action; it does not automatically erase retained results.

`python -m hyperreview.d1_shadow --config <private-config> --status` lists local
receipts. Without `--status` or `--job`, one tick looks for newly completed
previews. Installation and model paths are host configuration, not project defaults.
The owner-private JSON config contains `schema` (`hyperreview.d1-shadow.v1`),
absolute `input_root`, `output_root`, `python`, `model_path`, `hf_home`,
`tmp_dir`, and `not_before` (Unix seconds). `python` points to the isolated
Transformers environment; the scheduler process uses the normal HyperReview
environment. A missing model, MPS device, preview, or input is recorded as a
shadow failure and has no effect on the review worker.
