import argparse
import hashlib
import sys
from pathlib import Path

from .intake import IntakeError, collect, digest, encoded, save
from .model_contract import ContractError, prepare_request
from .storage import StorageError, read_json, write_bundle


def main():
    parser = argparse.ArgumentParser(description="Prepare and validate local PR explanations.")
    commands = parser.add_subparsers(dest="command", required=True)
    review = commands.add_parser("review")
    review.add_argument("--repo", required=True)
    review.add_argument("--pr", required=True, type=int)
    review.add_argument("--preview", action="store_true", required=True)
    review.add_argument(
        "--output-root", type=Path,
        default=Path.home() / ".local/share/hyperreview/evidence",
    )
    prepare = commands.add_parser("prepare", help="Prepare a filtered model request without inference")
    prepare.add_argument("--evidence", required=True, type=Path)
    prepare.add_argument("--include-path", action="append")
    prepare.add_argument("--max-source-bytes", type=int, default=4096)
    prepare.add_argument("--output-root", type=Path,
                         default=Path.home() / ".local/share/hyperreview/requests")
    generation = commands.add_parser("generate", help="Propose a result with Codex (Luna 6 low by default)")
    generation.add_argument("--request", required=True, type=Path)
    generation.add_argument("--provider", default="codex", choices=("codex", "lmstudio", "ollama"))
    generation.add_argument("--endpoint")
    generation.add_argument("--model")
    generation.add_argument("--reasoning-effort", choices=("low", "medium", "high"))
    generation.add_argument("--codex-executable", type=Path)
    generation.add_argument("--allow-cloud-source", action="store_true",
                            help="Acknowledge sending filtered source to the Codex cloud service")
    generation.add_argument("--instruction-role", choices=("system", "developer"))
    generation.add_argument("--context-tokens", type=int)
    generation.add_argument("--max-tokens", type=int)
    generation.add_argument("--timeout-seconds", type=int, default=120)
    generation.add_argument("--output-root", type=Path,
                            default=Path.home() / ".local/share/hyperreview/generated")
    compilation = commands.add_parser("compile", help="Validate paired projections and render a private preview")
    compilation.add_argument("--evidence", required=True, type=Path)
    compilation.add_argument("--request", required=True, type=Path)
    compilation.add_argument("--result", required=True, type=Path)
    compilation.add_argument("--generation-receipt", required=True, type=Path)
    compilation.add_argument("--compiler", required=True, type=Path)
    compilation.add_argument("--compiler-sha256", required=True)
    compilation.add_argument("--timeout-seconds", type=int, default=60)
    compilation.add_argument("--output-root", type=Path,
                             default=Path.home() / ".local/share/hyperreview/previews")
    tracking = commands.add_parser("track", help="Deliver metadata-only receipts to local MLflow")
    tracking_mode = tracking.add_mutually_exclusive_group(required=True)
    tracking_mode.add_argument("--bundle", type=Path)
    tracking_mode.add_argument("--reconcile", action="store_true")
    tracking.add_argument("--runtime-python", type=Path,
                          default=Path.home() / ".local/share/hyperreview/runtime/bin/python")
    tracking.add_argument("--database", type=Path,
                          default=Path.home() / ".local/share/hyperreview/mlflow/tracking.db")
    tracking.add_argument("--artifacts-root", type=Path,
                          default=Path.home() / ".local/share/hyperreview/mlflow/artifacts")
    tracking.add_argument("--spool-root", type=Path,
                          default=Path.home() / ".local/share/hyperreview/tracking-spool")
    tracking.add_argument("--timeout-seconds", type=int, default=120)
    feedback = commands.add_parser("feedback", help="Save a local assessment of one compact preview")
    feedback.add_argument("--bundle", required=True, type=Path)
    feedback.add_argument("--assessment", required=True, choices=("ok", "not_ok"))
    feedback.add_argument("--note")
    feedback.add_argument("--expected-preview-sha256")
    feedback.add_argument("--output-root", type=Path,
                          default=Path.home() / ".local/share/hyperreview/feedback")
    publication = commands.add_parser("publish-plan", help="Check live PR state and prepare a local comment dry-run")
    publication.add_argument("--bundle", required=True, type=Path)
    publication.add_argument("--expected-preview-sha256", required=True)
    publication.add_argument("--output-root", type=Path,
                             default=Path.home() / ".local/share/hyperreview/publication-plans")
    publish = commands.add_parser("publish", help="Publish one explicitly authorized reviewed comment")
    publish.add_argument("--plan-dir", required=True, type=Path)
    publish.add_argument("--expected-plan-sha256", required=True)
    publish.add_argument("--expected-comment-sha256", required=True)
    publish.add_argument("--authorize-repository", required=True)
    publish.add_argument("--authorize-mode", required=True, choices=("comment",))
    publish.add_argument("--state-root", type=Path,
                         default=Path.home() / ".local/share/hyperreview/publication-state")
    pilot = commands.add_parser("pilot", help="Run controlled boundaries and prepare an unfilled human worksheet")
    pilot.add_argument("--compiler", required=True, type=Path)
    pilot.add_argument("--compiler-sha256", required=True)
    pilot.add_argument("--output-root", type=Path,
                       default=Path.home() / ".local/share/hyperreview/pilot")
    args = parser.parse_args()
    try:
        if args.command == "publish-plan":
            from .publication import PublicationError, plan_publication
            try:
                destination, plan = plan_publication(
                    args.bundle, expected_preview_sha256=args.expected_preview_sha256,
                    output_root=args.output_root)
            except (PublicationError, IntakeError, StorageError, ContractError,
                    OSError, ValueError, KeyError, TypeError) as error:
                print(f"HyperReview: {type(error).__name__}; publication plan was not saved", file=sys.stderr)
                return 1
            print(f"Publication dry-run: {destination / 'plan.json'}")
            print(f"Comment draft: {destination / 'comment.md'}")
            print("Plan SHA256: " + hashlib.sha256((destination / "plan.json").read_bytes()).hexdigest())
            print("Comment SHA256: " + hashlib.sha256((destination / "comment.md").read_bytes()).hexdigest())
            print(f"Status: {plan['status']}; GitHub writes: 0")
            if plan["blockers"]:
                print("Blocked: " + ", ".join(plan["blockers"]))
            return 0 if plan["status"] == "ready" else 2
        if args.command == "publish":
            from .publication import PublicationError, publish_comment
            try:
                receipt = publish_comment(
                    args.plan_dir, expected_plan_sha256=args.expected_plan_sha256,
                    expected_comment_sha256=args.expected_comment_sha256,
                    authorized_repository=args.authorize_repository,
                    authorized_mode=args.authorize_mode, state_root=args.state_root)
            except (PublicationError, IntakeError, StorageError, OSError,
                    ValueError, KeyError, TypeError) as error:
                print(f"HyperReview: {type(error).__name__}; publication did not complete", file=sys.stderr)
                return 1
            print(f"Publication: {receipt['status']}; comment ID: {receipt['comment_id']}")
            return 0 if receipt["status"] in ("published", "already_published") else 2
        if args.command == "feedback":
            from .feedback import FeedbackError, save_feedback
            try:
                destination = save_feedback(
                    args.bundle, args.assessment, note=args.note,
                    expected_preview_sha256=args.expected_preview_sha256,
                    output_root=args.output_root)
            except (FeedbackError, StorageError, ContractError, OSError, ValueError, KeyError, TypeError) as error:
                print(f"HyperReview: {type(error).__name__}; feedback was not saved", file=sys.stderr)
                return 1
            print(f"Feedback saved: {destination / 'feedback.json'}")
            print(f"Assessment: {args.assessment}; local only; no publication performed")
            return 0
        if args.command == "pilot":
            from .pilot import run_pilot
            completed = run_pilot(args.compiler, args.compiler_sha256, args.output_root)
            print(f"Controlled cases: {completed['destination']}")
            print(f"Expected validator outcomes: {'matched' if completed['all_expected_outcomes_matched'] else 'FAILED'}")
            print("Human accuracy, missed violations and review time remain unmeasured")
            return 0 if completed["all_expected_outcomes_matched"] else 1
        if args.command == "track":
            from .tracking import TrackingError, pending_events, reconcile, update_bundle_tracking
            options = {"spool_root": args.spool_root, "runtime_python": args.runtime_python,
                       "database": args.database, "artifacts_root": args.artifacts_root,
                       "timeout_seconds": args.timeout_seconds}
            receipt = None
            try:
                if args.bundle:
                    event = update_bundle_tracking(args.bundle)
                else:
                    event = next(pending_events(args.spool_root), None)
                    if event is None:
                        print("Tracking outbox is empty")
                        return 0
                receipt = reconcile(event, **options)
                if args.bundle:
                    update_bundle_tracking(args.bundle, receipt)
                    from .render import render_preview, render_compact_preview
                    from .tracking import _atomic_bytes
                    request = read_json(args.bundle / "request.json")
                    result = read_json(args.bundle / "result.json", max_bytes=1024 * 1024)
                    compiler_receipt = read_json(args.bundle / "compiler-receipt.json")
                    diff = read_json(args.bundle / "diff.json", max_bytes=1024 * 1024)
                    preview = render_preview(request, result, compiler_receipt, diff,
                                             tracking_status="confirmed")
                    # Private bundle is operator-controlled; do not follow an artifact symlink.
                    preview_path = args.bundle / "preview.md"
                    if preview_path.is_symlink():
                        raise TrackingError("Preview output must not be a symlink")
                    compact_path = args.bundle / "preview-compact.md"
                    if compact_path.is_symlink():
                        raise TrackingError("Preview output must not be a symlink")
                    compact = render_compact_preview(
                        request, result, compiler_receipt, diff, tracking_status="confirmed")
                    _atomic_bytes(preview_path, preview)
                    _atomic_bytes(compact_path, compact)
                print(f"Tracking confirmed: run {receipt['run_id']}, trace {receipt['trace_id']}")
                print("Claims remain inferred; no publication performed")
                return 0
            except (TrackingError, StorageError, ContractError, OSError, ValueError, KeyError, TypeError) as error:
                status = "tracking confirmed; preview refresh incomplete" if receipt is not None else "tracking remains pending"
                detail = str(error) if isinstance(error, TrackingError) else type(error).__name__
                print(f"HyperReview: {detail}; {status}", file=sys.stderr)
                return 1
        if args.command == "compile":
            from .compiled_preview import PreviewError, compile_preview
            from .render import render_preview, render_compact_preview
            import json
            evidence = read_json(args.evidence)
            request = read_json(args.request)
            selection = request["source_selection"]
            rebuilt = prepare_request(evidence, max_source_bytes=selection["max_source_bytes"],
                                      include_paths=selection["include_paths"])
            if rebuilt != request:
                raise ContractError("Request does not match this evidence and selection")
            result = read_json(args.result, max_bytes=1024 * 1024)
            generation_receipt = read_json(args.generation_receipt)
            if (generation_receipt.get("stage") != "model_generated"
                    or generation_receipt.get("request_digest") != request["request_digest"]
                    or generation_receipt.get("result_digest") != digest(result)):
                raise ContractError("Generation receipt does not bind this request and result")
            try:
                compiled = compile_preview(request, result, compiler=args.compiler,
                                           compiler_sha256=args.compiler_sha256,
                                           timeout_seconds=args.timeout_seconds)
            except PreviewError as error:
                print(f"HyperReview: {error}; no validated preview saved", file=sys.stderr)
                return 1
            artifacts = compiled["artifacts"]
            semantic_diff = json.loads(artifacts["diff.json"])
            artifacts["preview.md"] = render_preview(request, result, compiled["receipt"], semantic_diff)
            artifacts["preview-compact.md"] = render_compact_preview(
                request, result, compiled["receipt"], semantic_diff)
            artifacts["evidence.json"] = encoded(evidence)
            artifacts["generation-receipt.json"] = encoded(generation_receipt)
            from uuid import uuid4
            artifacts["metadata.json"] = encoded({
                "schema": "hyperreview.preview.v1", "stage": "projections_validated",
                "tracking_correlation_id": str(uuid4()), "tracking_status": "not_started",
                "request_digest": request["request_digest"], "result_digest": digest(result),
                "delivery_mode": "preview", "attempt": 1,
            })
            destination = write_bundle(artifacts, args.output_root)
            print(f"Validated structural preview: {destination / 'preview-compact.md'}")
            print("Stage: projections_validated; claims remain inferred; tracking not started")
            return 0
        if args.command == "generate":
            from .local_provider import ProviderConfig, ProviderError, generate
            request = read_json(args.request)
            if args.provider == "codex":
                from .codex_provider import CodexConfig, CodexError, generate as generate_codex
                if not args.allow_cloud_source:
                    parser.error("Codex requires --allow-cloud-source to acknowledge source transmission")
                if any(value is not None for value in
                       (args.endpoint, args.instruction_role, args.context_tokens, args.max_tokens)):
                    parser.error("Codex does not accept local HTTP endpoint, role, context or output-token options")
                config = CodexConfig(model=args.model or "gpt-6-luna",
                                     reasoning_effort=args.reasoning_effort or "low",
                                     executable=str(args.codex_executable) if args.codex_executable is not None else None,
                                     timeout_seconds=args.timeout_seconds,
                                     allow_cloud_source=args.allow_cloud_source)
                generator = generate_codex
                provider_errors = (CodexError,)
            else:
                if args.allow_cloud_source:
                    parser.error("--allow-cloud-source is only supported with --provider codex")
                if args.reasoning_effort is not None or args.codex_executable is not None:
                    parser.error("Codex executable and reasoning options require --provider codex")
                if not args.model:
                    parser.error("Local HTTP generation requires --model")
                endpoint = args.endpoint or {
                    "lmstudio": "http://127.0.0.1:1234/v1",
                    "ollama": "http://127.0.0.1:11434/api",
                }[args.provider]
                config = ProviderConfig(args.provider, endpoint, args.model,
                                        args.context_tokens if args.context_tokens is not None else 8192,
                                        args.max_tokens if args.max_tokens is not None else 1024,
                                        args.timeout_seconds, args.instruction_role or "system")
                generator = generate
                provider_errors = (ProviderError,)
            try:
                proposed = generator(request, config)
            except provider_errors as error:
                print(f"HyperReview: {error}; no result bundle saved", file=sys.stderr)
                return 1
            receipt = {**proposed["receipt"], "stage": "model_generated",
                       "hypercode_validation": "not_started", "tracking_status": "not_started"}
            destination = write_bundle({"request.json": encoded(request),
                                        "composition-plan.json": encoded(proposed["plan"]),
                                        "result.json": encoded(proposed["result"]),
                                        "receipt.json": encoded(receipt)}, args.output_root)
            print(f"Proposed result: {destination / 'result.json'}")
            print(f"Receipt: {destination / 'receipt.json'}")
            print("Stage: model_generated; Hypercode validation and tracking not started")
            return 0
        if args.command == "prepare":
            request = prepare_request(read_json(args.evidence),
                                      max_source_bytes=args.max_source_bytes,
                                      include_paths=args.include_path)
            destination = write_bundle({"request.json": encoded(request)}, args.output_root)
            print(f"Prepared request: {destination / 'request.json'}")
            print(f"Included records: {len(request['sources'])}; omissions: {len(request['omissions'])}")
            print("Stage: request_prepared; no provider or tracking call made")
            return 0
        pack = collect(args.repo, args.pr)
        destination = save(pack, args.output_root)
    except (IntakeError, ContractError, StorageError, OSError, ValueError, KeyError, TypeError) as error:
        # API output and source text are never interpolated into diagnostics.
        print(f"HyperReview: {type(error).__name__}: intake did not complete", file=sys.stderr)
        if isinstance(error, (IntakeError, StorageError)):
            print(str(error), file=sys.stderr)
        return 1
    print(f"Evidence preview: {destination / 'preview.md'}")
    print(f"Pack: {destination / 'evidence.json'}")
    print("Stage: evidence_collected; architecture analysis and tracking not started")
    return 0


if __name__ == "__main__":
    sys.exit(main())
