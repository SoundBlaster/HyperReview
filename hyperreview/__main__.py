import argparse
import sys
from pathlib import Path

from .intake import IntakeError, collect, save


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
    args = parser.parse_args()
    try:
        pack = collect(args.repo, args.pr)
        destination = save(pack, args.output_root)
    except (IntakeError, OSError, ValueError, KeyError, TypeError) as error:
        # API output and source text are never interpolated into diagnostics.
        print(f"HyperReview: {type(error).__name__}: intake did not complete", file=sys.stderr)
        if isinstance(error, IntakeError):
            print(str(error), file=sys.stderr)
        return 1
    print(f"Evidence preview: {destination / 'preview.md'}")
    print(f"Pack: {destination / 'evidence.json'}")
    print("Stage: evidence_collected; architecture analysis and tracking not started")
    return 0


if __name__ == "__main__":
    sys.exit(main())
