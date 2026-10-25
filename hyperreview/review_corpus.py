"""Freeze review observations locally; curate criteria separately from feedback.

No GitHub access, inference, SDK export or automatic promotion of model feedback.
Captured packets are immutable observations, not authenticated human judgments.
"""

import argparse
import hashlib
from pathlib import Path, PurePosixPath
import re
import sys

from . import intake, review_evaluation as evaluation
from .evaluation_delivery import EvaluationDeliveryError, _trusted_input_file, _trusted_path
from .storage import StorageError, read_json, write_bundle


SCHEMA = "hyperreview.review-corpus.v1"
PACKET_SCHEMA = "hyperreview.corpus-observation.v1"
FEEDBACK_SCHEMA = "hyperreview.corpus-feedback.v1"
VALIDATOR_SCHEMA = "hyperreview.validator-observation.v1"
_FILES = ("request.json", "evidence.json", "result.json", "compiler-receipt.json",
          "generation-receipt.json", "before.hc", "after.hc", "before.ir.json", "after.ir.json")
_OPTIONAL = ("composition-plan.json", "preview-compact.md")
_URL = re.compile(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/pull/[1-9][0-9]*(?:#[A-Za-z0-9_-]+)?\Z")
require = evaluation.require


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _json(path):
    return read_json(_trusted_input_file(path), max_bytes=1024 * 1024)


def _case(case):
    evaluation.validate_suite({"schema": evaluation.SUITE_SCHEMA, "version": "corpus-case", "cases": [case]})


def _feedback(value):
    require(type(value) is dict and set(value) == {"schema", "source", "author_kind", "url", "body"}
            and value["schema"] == FEEDBACK_SCHEMA
            and value["source"] in ("github_review", "local_assessment")
            and value["author_kind"] in ("human", "agent", "model")
            and type(value["body"]) is str and 1 <= len(value["body"]) <= 16000,
            "Invalid feedback snapshot")
    url = value["url"]
    require((url is None and value["source"] == "local_assessment")
            or (type(url) is str and _URL.fullmatch(url)), "Invalid feedback source URL")
    return value


def capture(bundle, case, feedback, output_root):
    """Copy exact bounded artifacts, including supplied bytes, before another fix."""
    _case(case)
    _feedback(feedback)
    directory = _trusted_path(bundle, directory=True)
    frozen = evaluation.load_bundle(directory, projection=True)
    request = frozen["request"]
    require((request["repository"], request["pr"], request["merge_base_sha"], request["head_sha"])
            == (case["repository"], case["pr"], case["base"], case["head"]), "Corpus case revision mismatch")
    files = {}
    for name in _FILES + _OPTIONAL:
        path = directory / name
        if name in _OPTIONAL and not path.exists():
            require(not path.is_symlink(), "Invalid optional corpus artifact")
            continue
        path = _trusted_input_file(path)
        require(path.stat().st_size <= 1024 * 1024, "Corpus artifact exceeds limit")
        raw = path.read_bytes()
        require(len(raw) <= 1024 * 1024, "Corpus artifact exceeds limit")
        files[name] = raw
    observation = {"schema": PACKET_SCHEMA, "case": case, "feedback": feedback,
                   "label_status": "candidate", "artifact_digest": frozen["digest"],
                   "request_digest": request["request_digest"],
                   "files": {name: _sha(raw) for name, raw in files.items()},
                   "raw_attempts": "final_plan_only" if "composition-plan.json" in files else "unavailable"}
    observation["record_digest"] = intake.digest(observation)
    root = _trusted_path(output_root, directory=True, create=True)
    destination = write_bundle({**files, "observation.json": intake.encoded(observation)}, root)
    try:
        verify(destination)  # Catch a source mutation while copying; no live path dependency.
    except Exception:
        for name in (*files, "observation.json"):
            (destination / name).unlink(missing_ok=True)
        destination.rmdir()
        raise
    return {"path": str(destination), "record_digest": observation["record_digest"], "label_status": "candidate"}


def verify(packet):
    directory = _trusted_path(packet, directory=True)
    value = _json(directory / "observation.json")
    if type(value) is dict and value.get("schema") == VALIDATOR_SCHEMA:
        require(set(value) == {"schema", "feedback", "label_status", "files", "record_digest"}
                and value["label_status"] == "candidate" and type(value["files"]) is dict
                and set(value["files"]) == {"fixture.json"}, "Invalid validator observation")
        _feedback(value["feedback"])
        require(value["record_digest"] == intake.digest({k: v for k, v in value.items() if k != "record_digest"}),
                "Validator observation seal mismatch")
        fixture = _trusted_input_file(directory / "fixture.json")
        require(fixture.stat().st_size <= 1024 * 1024 and _sha(fixture.read_bytes()) == value["files"]["fixture.json"],
                "Validator fixture changed")
        _json(fixture)
        return value
    require(type(value) is dict and set(value) == {"schema", "case", "feedback", "label_status", "artifact_digest",
        "request_digest", "files", "raw_attempts", "record_digest"}
        and value["schema"] == PACKET_SCHEMA and value["label_status"] == "candidate", "Invalid corpus observation")
    require(value["record_digest"] == intake.digest({k: v for k, v in value.items() if k != "record_digest"}),
            "Corpus observation seal mismatch")
    _case(value["case"])
    _feedback(value["feedback"])
    files = value["files"]
    require(type(files) is dict and set(_FILES) <= set(files) <= set(_FILES + _OPTIONAL), "Invalid corpus files")
    for name, digest in files.items():
        path = _trusted_input_file(directory / name)
        require(path.stat().st_size <= 1024 * 1024 and _sha(path.read_bytes()) == digest, "Corpus artifact changed")
    loaded = evaluation.load_bundle(directory, projection=True)
    require(loaded["digest"] == value["artifact_digest"] and loaded["request"]["request_digest"] == value["request_digest"],
            "Corpus bundle changed")
    if "composition-plan.json" in files:
        plan = _json(directory / "composition-plan.json")
        require(type(plan) is dict and plan.get("request_digest") == value["request_digest"], "Plan/request mismatch")
        digest = loaded["generation"].get("provider_plan_digest")
        require(digest is None or digest == intake.digest(plan), "Plan/generation mismatch")
    case, request = value["case"], loaded["request"]
    require((case["repository"], case["pr"], case["base"], case["head"])
            == (request["repository"], request["pr"], request["merge_base_sha"], request["head_sha"]),
            "Corpus case revision mismatch")
    require(value["raw_attempts"] == ("final_plan_only" if "composition-plan.json" in files else "unavailable"),
            "Invalid raw attempt availability")
    return value


def capture_validator(fixture, feedback, output_root):
    """Keep validator counterexamples outside model-review populations."""
    _feedback(feedback)
    fixture = _trusted_input_file(fixture)
    _json(fixture)
    require(fixture.stat().st_size <= 1024 * 1024, "Validator fixture exceeds limit")
    raw = fixture.read_bytes()
    require(len(raw) <= 1024 * 1024, "Validator fixture exceeds limit")
    observation = {"schema": VALIDATOR_SCHEMA, "feedback": feedback, "label_status": "candidate",
                   "files": {"fixture.json": _sha(raw)}}
    observation["record_digest"] = intake.digest(observation)
    root = _trusted_path(output_root, directory=True, create=True)
    destination = write_bundle({"fixture.json": raw, "observation.json": intake.encoded(observation)}, root)
    verify(destination)
    return {"path": str(destination), "record_digest": observation["record_digest"], "label_status": "candidate"}


def validate_corpus(value):
    require(type(value) is dict and set(value) == {"schema", "version", "entries"}
            and value["schema"] == SCHEMA and evaluation._text(value["version"], 80)
            and type(value["entries"]) is list and 1 <= len(value["entries"]) <= 64, "Invalid review corpus")
    seen, cases, groups = set(), set(), {}
    for entry in value["entries"]:
        require(type(entry) is dict and set(entry) == {"id", "kind", "split", "group", "used_for_tuning",
            "case", "fixture", "records", "adjudication", "tags", "origin_urls"}, "Invalid corpus entry")
        require(type(entry["id"]) is str and re.fullmatch(r"sample-[0-9]{3}", entry["id"])
                and entry["id"] not in seen, "Invalid or duplicate sample ID")
        seen.add(entry["id"])
        require(entry["kind"] in ("model_review", "validator") and entry["split"] in ("development", "holdout")
                and type(entry["used_for_tuning"]) is bool
                and not (entry["split"] == "holdout" and entry["used_for_tuning"]), "Invalid corpus split")
        group = entry["group"]
        require(type(group) is str and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#[1-9][0-9]*", group),
                "Invalid corpus group")
        require(groups.setdefault(group, entry["split"]) == entry["split"], "PR group leaks across splits")
        adjudication = entry["adjudication"]
        require(type(adjudication) is dict and set(adjudication) == {"status", "assessor_kind", "rationale"}
                and adjudication["status"] in ("candidate", "source_checked")
                and adjudication["assessor_kind"] in ("human", "agent", "model")
                and evaluation._text(adjudication["rationale"], 2000)
                and not (adjudication["status"] == "source_checked" and adjudication["assessor_kind"] == "model"),
                "Invalid corpus adjudication")
        require(type(entry["records"]) is list and len(entry["records"]) <= 8
                and all(type(d) is str and evaluation.SHA.fullmatch(d) for d in entry["records"])
                and len(set(entry["records"])) == len(entry["records"]), "Invalid record seals")
        require(type(entry["tags"]) is list and 1 <= len(entry["tags"]) <= 8
                and all(type(t) is str and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", t) for t in entry["tags"]), "Invalid tags")
        require(type(entry["origin_urls"]) is list and len(entry["origin_urls"]) <= 8
                and all(type(u) is str and _URL.fullmatch(u) for u in entry["origin_urls"]), "Invalid origin URLs")
        if entry["kind"] == "model_review":
            _case(entry["case"])
            case = entry["case"]
            require(case["id"] not in cases and group == f"{case['repository']}#{case['pr']}"
                    and entry["fixture"] is None, "Invalid model case identity")
            cases.add(case["id"])
        else:
            fixture = entry["fixture"]
            require(entry["case"] is None and type(fixture) is dict
                    and set(fixture) == {"path", "sha256"} and type(fixture["path"]) is str
                    and fixture["path"].startswith("evaluations/fixtures/")
                    and ".." not in PurePosixPath(fixture["path"]).parts
                    and type(fixture["sha256"]) is str and evaluation.SHA.fullmatch(fixture["sha256"]),
                    "Invalid validator fixture")
    return value


def model_suite(corpus, records_root, *, split="development", case_ids=None):
    """Select curated model cases with available sealed packets; never validators."""
    validate_corpus(corpus)
    require(split in ("development", "holdout"), "Invalid selected split")
    selected = [e for e in corpus["entries"] if e["kind"] == "model_review" and e["split"] == split
                and e["adjudication"]["status"] == "source_checked"]
    if case_ids is not None:
        require(type(case_ids) is list and 1 <= len(case_ids) <= 16
                and all(type(i) is str and evaluation.ID.fullmatch(i) for i in case_ids)
                and len(set(case_ids)) == len(case_ids), "Invalid model case selection")
        require(set(case_ids) <= {e["case"]["id"] for e in selected}, "Selected model case is unavailable")
        selected = [e for e in selected if e["case"]["id"] in case_ids]
    require(selected, "No curated model cases in selected split")
    root = _trusted_path(records_root, directory=True)
    paths = sorted(root.iterdir())
    require(len(paths) <= 512, "Corpus registry exceeds scan limit")
    records = {}
    for path in paths:
        if path.is_dir() or path.is_symlink():
            packet = verify(path)
            records[packet["record_digest"]] = packet
    for entry in selected:
        require(entry["records"] and all(d in records and records[d].get("case") == entry["case"]
                                        for d in entry["records"]), "Curated case needs matching frozen observations")
    return evaluation.validate_suite({"schema": evaluation.SUITE_SCHEMA,
        "version": corpus["version"] + "-" + split, "cases": [entry["case"] for entry in selected]})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    capture_parser = commands.add_parser("capture")
    for name in ("bundle", "suite", "feedback", "output-root"):
        capture_parser.add_argument("--" + name, type=Path, required=True)
    capture_parser.add_argument("--case-id", required=True)
    validator_parser = commands.add_parser("capture-validator")
    for name in ("fixture", "feedback", "output-root"):
        validator_parser.add_argument("--" + name, type=Path, required=True)
    export_parser = commands.add_parser("suite")
    export_parser.add_argument("--corpus", type=Path, required=True)
    export_parser.add_argument("--records-root", type=Path, required=True)
    export_parser.add_argument("--split", choices=("development", "holdout"), default="development")
    export_parser.add_argument("--case-id", action="append", dest="case_ids")
    args = parser.parse_args(argv)
    try:
        if args.command == "capture":
            suite = evaluation.validate_suite(_json(args.suite))
            cases = [c for c in suite["cases"] if c["id"] == args.case_id]
            require(len(cases) == 1, "Unknown corpus case")
            result = capture(args.bundle, cases[0], _json(args.feedback), args.output_root)
        elif args.command == "capture-validator":
            result = capture_validator(args.fixture, _json(args.feedback), args.output_root)
        else:
            result = model_suite(_json(args.corpus), args.records_root, split=args.split, case_ids=args.case_ids)
    except (evaluation.ReviewEvaluationError, EvaluationDeliveryError, StorageError, OSError, ValueError, TypeError):
        print("HyperReview: corpus input, lineage or selection rejected", file=sys.stderr)
        return 2
    print(intake.encoded(result).decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
