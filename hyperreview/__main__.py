import argparse
import sys
from pathlib import Path

from .intake import IntakeError, collect, encoded, save
from .model_contract import ContractError, prepare_request
from .storage import StorageError, read_json, write_bundle


def main():
    parser = argparse.ArgumentParser(description="Collect pinned PR evidence locally.")
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
    args = parser.parse_args()
    try:
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
            except ProviderError:
                print("HyperReview: local inference did not complete; no result bundle saved", file=sys.stderr)
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
