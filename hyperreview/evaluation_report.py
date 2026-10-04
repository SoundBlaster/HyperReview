"""Generate bounded local evaluation reports from deterministic boundary fixtures."""

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import statistics
import sys

from .storage import StorageError, read_json, write_bundle


INPUT_SCHEMA = "hyperreview.evaluation.v1"
SUMMARY_SCHEMA = "hyperreview.evaluation-report.v1"
METRIC_DEFINITION_VERSION = "boundary-v2"
ASSESSOR_TYPE = "deterministic"
EVIDENTLY_VERSION = "0.7.23"
MAX_INPUT_BYTES = 64 * 1024
MAX_OUTPUT_BYTES = 16 * 1024 * 1024
CASE_ID = re.compile(r"case-[0-9]{3}\Z")
DATASET_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
METRIC_FIELDS = (
    "projection_grammar_valid",
    "projection_reference_valid",
    "validator_expected_outcome_match",
    "structural_change_count",
    "omissions",
    "elapsed_ms",
)
ROW_FIELDS = frozenset(("case_id", *METRIC_FIELDS))


class EvaluationReportError(Exception):
    """Raised when deterministic assessment data cannot be reported safely."""


def _require(condition, message):
    if not condition:
        raise EvaluationReportError(message)


def _encoded(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError, OverflowError) as error:
        raise EvaluationReportError("Assessment is not valid bounded JSON data") from error


def validate_assessment(assessment):
    """Validate the exact deterministic evaluation input schema."""
    _require(type(assessment) is dict
             and set(assessment) == {
                 "schema", "dataset_digest", "metric_definition_version",
                 "assessor_type", "records",
             }, "Assessment has missing or unknown fields")
    _require(type(assessment["schema"]) is str and assessment["schema"] == INPUT_SCHEMA,
             "Assessment schema is unsupported")
    _require(type(assessment["dataset_digest"]) is str
             and DATASET_DIGEST.fullmatch(assessment["dataset_digest"]) is not None,
             "Assessment dataset digest is invalid")
    _require(type(assessment["metric_definition_version"]) is str
             and assessment["metric_definition_version"] == METRIC_DEFINITION_VERSION,
             "Assessment metric definition version is unsupported")
    _require(type(assessment["assessor_type"]) is str
             and assessment["assessor_type"] == ASSESSOR_TYPE,
             "Assessment must use the deterministic assessor")
    records = assessment["records"]
    _require(type(records) is list and 5 <= len(records) <= 10,
             "Assessment must contain 5 through 10 records")
    seen_ids = set()
    for record in records:
        _require(type(record) is dict and set(record) == ROW_FIELDS,
                 "Assessment record has missing or unknown fields")
        case_id = record["case_id"]
        _require(type(case_id) is str and CASE_ID.fullmatch(case_id) is not None,
                 "Assessment case ID is invalid")
        _require(case_id not in seen_ids, "Assessment case IDs must be unique")
        seen_ids.add(case_id)
        for field in ("projection_grammar_valid", "projection_reference_valid",
                      "validator_expected_outcome_match"):
            value = record[field]
            nullable = field in ("projection_grammar_valid", "projection_reference_valid")
            _require((nullable and value is None) or (type(value) is int and value in (0, 1)),
                     f"Assessment {field} must be integer 0 or 1")
        changes = record["structural_change_count"]
        _require(changes is None or (type(changes) is int and 0 <= changes <= 1000),
                 "Assessment structural_change_count is invalid")
        omissions = record["omissions"]
        _require(type(omissions) is int and 0 <= omissions <= 60,
                 "Assessment omissions is invalid")
        elapsed = record["elapsed_ms"]
        _require(type(elapsed) is int and 0 <= elapsed <= 300000,
                 "Assessment elapsed_ms is invalid")
    _require(len(_encoded(assessment)) <= MAX_INPUT_BYTES,
             "Assessment exceeds the 64 KiB input limit")
    return assessment


def _assessment_from_path(path):
    try:
        with Path(path).open("rb") as source:
            raw = source.read(MAX_INPUT_BYTES + 1)
    except OSError as error:
        raise EvaluationReportError("Assessment input could not be read") from error
    _require(len(raw) <= MAX_INPUT_BYTES, "Assessment exceeds the 64 KiB input limit")

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate field")
            result[key] = value
        return result

    def reject_constant(_value):
        raise ValueError("non-finite number")

    try:
        assessment = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object,
                                parse_constant=reject_constant)
    except (UnicodeError, ValueError, TypeError, RecursionError, OverflowError) as error:
        raise EvaluationReportError("Assessment input is not valid strict JSON") from error
    return validate_assessment(assessment)


def _evidently_factory(rows, metric_columns):
    # Set both supported telemetry flags before importing Evidently: its package
    # initialization constructs the telemetry logger during import.
    os.environ["DO_NOT_TRACK"] = "1"
    os.environ["EVIDENTLY_DISABLE_TELEMETRY"] = "1"
    try:
        installed_version = importlib.metadata.version("evidently")
    except importlib.metadata.PackageNotFoundError as error:
        raise EvaluationReportError("Evidently 0.7.23 is not installed") from error
    _require(installed_version == EVIDENTLY_VERSION,
             "Evaluation reports require Evidently 0.7.23")
    try:
        import pandas as pd
        from evidently import Report
        from evidently.metrics import MeanValue

        frame = pd.DataFrame(rows, columns=list(metric_columns))
        report = Report([MeanValue(column=column) for column in metric_columns])
        snapshot = report.run(frame)
        report_json = snapshot.json().encode("utf-8")
        report_html = snapshot.get_html_str(as_iframe=False).encode("utf-8")
    except Exception as error:
        # The underlying SDK exception can include data or environment details.
        raise EvaluationReportError("Evidently could not render the local report") from error
    return {"sdk_version": installed_version, "report_json": report_json,
            "report_html": report_html}


def _summary(assessment):
    means = {}
    coverage = {}
    for field in METRIC_FIELDS:
        values = [record[field] for record in assessment["records"]
                  if record[field] is not None]
        means[field] = statistics.mean(values) if values else None
        coverage[field] = {"measured_count": len(values),
                           "record_count": len(assessment["records"])}
    return {
        "schema": SUMMARY_SCHEMA,
        "dataset_digest": assessment["dataset_digest"],
        "metric_definition_version": METRIC_DEFINITION_VERSION,
        "assessor_type": ASSESSOR_TYPE,
        "assessment_kind": "deterministic_boundary_fixtures",
        "human_evaluation": "awaiting_independent_reviewers",
        "evidently_version": EVIDENTLY_VERSION,
        "record_count": len(assessment["records"]),
        "means": means,
        "coverage": coverage,
    }


def create_report(assessment, output_root, sdk_factory=None):
    """Generate metadata-only Evidently artifacts in a private local bundle.

    ``sdk_factory`` is a test seam receiving only numeric row dictionaries and
    the fixed metric-column tuple. It must return bytes under ``report_json`` and
    ``report_html``, plus ``sdk_version``.
    """
    assessment = validate_assessment(assessment)
    _require(isinstance(output_root, (str, Path)) and Path(output_root).is_absolute(),
             "Output root must be an absolute path")
    metric_columns = tuple(field for field in METRIC_FIELDS
                           if any(row[field] is not None for row in assessment["records"]))
    numeric_rows = [{field: row[field] for field in metric_columns}
                    for row in assessment["records"]]
    factory = sdk_factory or _evidently_factory
    try:
        sdk_output = factory(numeric_rows, metric_columns)
    except EvaluationReportError:
        raise
    except Exception as error:
        raise EvaluationReportError("Local report generation failed") from error
    _require(type(sdk_output) is dict
             and set(sdk_output) == {"sdk_version", "report_json", "report_html"},
             "Report renderer returned an invalid result")
    _require(sdk_output["sdk_version"] == EVIDENTLY_VERSION,
             "Evaluation reports require Evidently 0.7.23")
    report_json = sdk_output["report_json"]
    report_html = sdk_output["report_html"]
    _require(type(report_json) is bytes and type(report_html) is bytes,
             "Report renderer must return report bytes")
    _require(len(report_json) <= MAX_OUTPUT_BYTES and len(report_html) <= MAX_OUTPUT_BYTES,
             "Generated report exceeds the 16 MiB artifact limit")
    summary = _summary(assessment)
    artifacts = {
        "report.json": report_json,
        "report.html": report_html,
        "summary.json": _encoded(summary),
        "assessments.json": _encoded(assessment),
    }
    _require(len(artifacts["summary.json"]) <= 64 * 1024
             and len(artifacts["assessments.json"]) <= MAX_INPUT_BYTES,
             "Generated metadata exceeds its output size limit")
    try:
        bundle_path = write_bundle(artifacts, output_root)
    except StorageError as error:
        raise EvaluationReportError("Private report bundle could not be saved") from error
    return {"path": bundle_path, "summary": summary,
            "report_sha256": hashlib.sha256(report_json).hexdigest()}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Create a local metadata-only evaluation report.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    args = parser.parse_args(argv)
    if not args.input.is_absolute() or not args.output_root.is_absolute():
        print("HyperReview: input and output-root must be absolute paths", file=sys.stderr)
        return 2
    try:
        assessment = _assessment_from_path(args.input)
        output = create_report(assessment, args.output_root)
    except (EvaluationReportError, OSError, ValueError) as error:
        print(f"HyperReview: {error}", file=sys.stderr)
        return 1
    print(f"Local evaluation report: {output['path']}")
    print("Assessment type: deterministic boundary fixtures")
    print("Human evaluation: awaiting independent reviewers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
