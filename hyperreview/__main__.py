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
    args = parser.parse_args()
    try:
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
