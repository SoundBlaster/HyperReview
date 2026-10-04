import argparse
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
    generation = commands.add_parser("generate", help="Propose a result using an explicit local HTTP model")
    generation.add_argument("--request", required=True, type=Path)
    generation.add_argument("--provider", required=True, choices=("lmstudio", "ollama"))
    generation.add_argument("--endpoint")
    generation.add_argument("--model", required=True)
    generation.add_argument("--context-tokens", type=int, default=8192)
    generation.add_argument("--max-tokens", type=int, default=1024)
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
    args = parser.parse_args()
    try:
        if args.command == "track":
            from .tracking import TrackingError, pending_events, reconcile, update_bundle_tracking
            options = {"spool_root": args.spool_root, "runtime_python": args.runtime_python,
                       "database": args.database, "artifacts_root": args.artifacts_root,
                       "timeout_seconds": args.timeout_seconds}
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
                    from .render import render_preview
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
                    _atomic_bytes(preview_path, preview)
                print(f"Tracking confirmed: run {receipt['run_id']}, trace {receipt['trace_id']}")
                print("Claims remain inferred; no publication performed")
                return 0
            except TrackingError as error:
                print(f"HyperReview: {error}; tracking remains pending", file=sys.stderr)
                return 1
        if args.command == "compile":
            from .compiled_preview import PreviewError, compile_preview
            from .render import render_preview
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
            print(f"Validated structural preview: {destination / 'preview.md'}")
            print("Stage: projections_validated; claims remain inferred; tracking not started")
            return 0
        if args.command == "generate":
            from .local_provider import ProviderConfig, ProviderError, generate
            endpoint = args.endpoint or {
                "lmstudio": "http://127.0.0.1:1234/v1",
                "ollama": "http://127.0.0.1:11434/api",
            }[args.provider]
            config = ProviderConfig(args.provider, endpoint, args.model,
                                    args.context_tokens, args.max_tokens, args.timeout_seconds)
            request = read_json(args.request)
            try:
                proposed = generate(request, config)
            except ProviderError as error:
                print(f"HyperReview: {error}; no result bundle saved", file=sys.stderr)
                return 1
            receipt = {**proposed["receipt"], "stage": "model_generated",
                       "hypercode_validation": "not_started", "tracking_status": "not_started"}
            destination = write_bundle({"request.json": encoded(request),
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
