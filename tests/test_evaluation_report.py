import hashlib
import json
import tempfile
from pathlib import Path
import unittest

from hyperreview.evaluation_report import (
    ASSESSOR_TYPE,
    EVIDENTLY_VERSION,
    INPUT_SCHEMA,
    MAX_INPUT_BYTES,
    MAX_OUTPUT_BYTES,
    METRIC_DEFINITION_VERSION,
    METRIC_FIELDS,
    EvaluationReportError,
    _assessment_from_path,
    create_report,
    validate_assessment,
)
from hyperreview.storage import read_json


def assessment(*, structural_change_count=2):
    rows = []
    for index in range(5):
        rows.append({
            "case_id": f"case-{index + 1:03d}",
            "projection_grammar_valid": 1,
            "projection_reference_valid": index % 2,
            "validator_expected_outcome_match": 1,
            "structural_change_count": structural_change_count,
            "omissions": index,
            "elapsed_ms": 100 + index,
        })
    return {
        "schema": INPUT_SCHEMA,
        "dataset_digest": "a" * 64,
        "metric_definition_version": METRIC_DEFINITION_VERSION,
        "assessor_type": ASSESSOR_TYPE,
        "records": rows,
    }


class FakeSDK:
    def __init__(self, *, report_json=b'{"fake":true}', report_html=b"<html>fixed</html>",
                 version=EVIDENTLY_VERSION):
        self.report_json = report_json
        self.report_html = report_html
        self.version = version
        self.rows = None
        self.columns = None

    def __call__(self, rows, columns):
        self.rows = rows
        self.columns = columns
        return {"sdk_version": self.version, "report_json": self.report_json,
                "report_html": self.report_html}


class ValidateAssessmentTests(unittest.TestCase):
    def test_accepts_controlled_metadata_and_optional_missing_change_count(self):
        value = assessment(structural_change_count=None)
        self.assertIs(validate_assessment(value), value)

    def test_rejects_extra_top_level_and_record_fields(self):
        value = assessment()
        value["source"] = "untrusted text"
        with self.assertRaises(EvaluationReportError):
            validate_assessment(value)
        value = assessment()
        value["records"][0]["model_response"] = "untrusted text"
        with self.assertRaises(EvaluationReportError):
            validate_assessment(value)

    def test_rejects_bad_schema_digest_assessor_and_metric_version(self):
        mutations = (
            ("schema", "other"),
            ("dataset_digest", "A" * 64),
            ("dataset_digest", "../unsafe"),
            ("assessor_type", "human"),
            ("metric_definition_version", "boundary-v1"),
        )
        for key, value in mutations:
            with self.subTest(key=key, value=value):
                item = assessment()
                item[key] = value
                with self.assertRaises(EvaluationReportError):
                    validate_assessment(item)

    def test_rejects_record_count_ids_and_duplicate_ids(self):
        for count in (0, 4, 11):
            item = assessment()
            if count < len(item["records"]):
                item["records"] = item["records"][:count]
            else:
                item["records"] += [dict(item["records"][0])
                                     for _ in range(count - len(item["records"]))]
                for index, row in enumerate(item["records"]):
                    row["case_id"] = f"case-{index + 1:03d}"
            with self.subTest(count=count), self.assertRaises(EvaluationReportError):
                validate_assessment(item)
        item = assessment()
        item["records"][1]["case_id"] = item["records"][0]["case_id"]
        with self.assertRaisesRegex(EvaluationReportError, "unique"):
            validate_assessment(item)
        for case_id in ("case-1", "case-0000", "Case-001", "case-../"):
            item = assessment()
            item["records"][0]["case_id"] = case_id
            with self.subTest(case_id=case_id), self.assertRaises(EvaluationReportError):
                validate_assessment(item)

    def test_rejects_boolean_float_and_out_of_range_metrics(self):
        invalid_rows = (
            ("projection_grammar_valid", True),
            ("projection_reference_valid", 1.0),
            ("validator_expected_outcome_match", 2),
            ("structural_change_count", -1),
            ("structural_change_count", 1001),
            ("omissions", 61),
            ("elapsed_ms", 300001),
        )
        for field, value in invalid_rows:
            item = assessment()
            item["records"][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(EvaluationReportError):
                validate_assessment(item)

    def test_allows_unmeasured_validity_fields_but_not_unmeasured_outcome(self):
        item = assessment()
        item["records"][0]["projection_grammar_valid"] = None
        item["records"][0]["projection_reference_valid"] = None
        self.assertIs(validate_assessment(item), item)
        item["records"][0]["validator_expected_outcome_match"] = None
        with self.assertRaises(EvaluationReportError):
            validate_assessment(item)

    def test_rejects_nan_and_duplicate_json_fields(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "input.json"
            path.write_text('{"x":NaN}', encoding="utf-8")
            with self.assertRaises(EvaluationReportError):
                _assessment_from_path(path)
            path.write_text('{"schema":"a","schema":"b"}', encoding="utf-8")
            with self.assertRaises(EvaluationReportError):
                _assessment_from_path(path)

    def test_rejects_input_above_64kib(self):
        item = assessment()
        item["records"][0]["case_id"] = "case-001"
        raw = json.dumps(item).encode("utf-8")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "input.json"
            path.write_bytes(raw + b" " * (MAX_INPUT_BYTES - len(raw) + 1))
            with self.assertRaisesRegex(EvaluationReportError, "64 KiB"):
                _assessment_from_path(path)


class CreateReportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="evaluation-report-test-")
        self.root = Path(self.temporary.name).resolve() / "reports"

    def tearDown(self):
        self.temporary.cleanup()

    def test_creates_private_metadata_only_bundle(self):
        fake = FakeSDK(report_json=b'{"metric":0.5}', report_html=b"<html>numeric report</html>")
        result = create_report(assessment(structural_change_count=None), self.root, fake)
        bundle = result["path"]
        self.assertEqual(set(path.name for path in bundle.iterdir()), {
            "report.json", "report.html", "summary.json", "assessments.json",
        })
        self.assertEqual(read_json(bundle / "assessments.json"), assessment(structural_change_count=None))
        self.assertEqual((bundle / "report.json").read_bytes(), fake.report_json)
        summary = read_json(bundle / "summary.json")
        self.assertEqual(summary["human_evaluation"], "awaiting_independent_reviewers")
        self.assertEqual(summary["assessment_kind"], "deterministic_boundary_fixtures")
        self.assertIsNone(summary["means"]["structural_change_count"])
        self.assertEqual(summary["record_count"], 5)
        self.assertEqual(result["report_sha256"], hashlib.sha256(fake.report_json).hexdigest())
        self.assertNotIn("accuracy", summary)
        self.assertNotIn("time_benefit", summary)

    def test_only_fixed_numeric_columns_reach_report_factory(self):
        fake = FakeSDK()
        create_report(assessment(), self.root, fake)
        self.assertEqual(fake.columns, METRIC_FIELDS)
        self.assertEqual(len(fake.rows), 5)
        self.assertTrue(all(set(row) == set(METRIC_FIELDS) for row in fake.rows))
        self.assertTrue(all(type(value) is int for row in fake.rows for value in row.values()))

    def test_nullable_count_is_not_coerced_to_zero(self):
        fake = FakeSDK()
        create_report(assessment(structural_change_count=None), self.root, fake)
        self.assertNotIn("structural_change_count", fake.columns)
        self.assertTrue(all("structural_change_count" not in row for row in fake.rows))

    def test_report_preserves_missing_values_and_reports_metric_coverage(self):
        value = assessment(structural_change_count=None)
        value["records"][0]["projection_reference_valid"] = None
        value["records"][0]["projection_grammar_valid"] = None
        fake = FakeSDK()
        result = create_report(value, self.root, fake)
        self.assertIn("projection_reference_valid", fake.columns)
        self.assertNotIn("structural_change_count", fake.columns)
        self.assertEqual(result["summary"]["means"]["projection_reference_valid"], 0.5)
        self.assertEqual(result["summary"]["coverage"]["projection_reference_valid"], {
            "measured_count": 4, "record_count": 5,
        })
        self.assertEqual(result["summary"]["coverage"]["projection_grammar_valid"], {
            "measured_count": 4, "record_count": 5,
        })
        self.assertEqual(result["summary"]["coverage"]["structural_change_count"], {
            "measured_count": 0, "record_count": 5,
        })

    def test_rejects_wrong_sdk_version_and_oversized_artifacts(self):
        with self.assertRaisesRegex(EvaluationReportError, "Evidently 0.7.23"):
            create_report(assessment(), self.root, FakeSDK(version="0.7.24"))
        too_large = FakeSDK(report_html=b"x" * (MAX_OUTPUT_BYTES + 1))
        with self.assertRaisesRegex(EvaluationReportError, "16 MiB"):
            create_report(assessment(), self.root, too_large)

    def test_output_root_must_be_absolute(self):
        with self.assertRaisesRegex(EvaluationReportError, "absolute"):
            create_report(assessment(), Path("relative"), FakeSDK())


if __name__ == "__main__":
    unittest.main()
