import csv
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from hyperreview import intake
from hyperreview.compiled_preview import CompilerCommandError, PreviewError
from hyperreview.pilot import CASES, run_pilot
from hyperreview.storage import read_json


EXPECTED_FAILURES = {
    "case-004": "Before IR roles do not match the identity map",
}


def expected_compilation(request, result, **kwargs):
    case = next(case for case in CASES
                if case["before_hc"] == result["before_hc"]
                and case["after_hc"] == result["after_hc"])
    if not case["accepted"]:
        if case["id"] == "case-002":
            raise CompilerCommandError("parse", 1, ("HC1001",))
        raise PreviewError(EXPECTED_FAILURES[case["id"]])
    return {"receipt": {"change_count": case["changes"]}}


class PilotTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="hyperreview-pilot-test-")
        self.output_root = Path(self.temporary.name).resolve() / "out"

    def tearDown(self):
        self.temporary.cleanup()

    def run_with(self, side_effect):
        with mock.patch("hyperreview.pilot.compile_preview", side_effect=side_effect) as compiler:
            result = run_pilot("/trusted/hypercode", "a" * 64, self.output_root)
        return result, compiler

    def test_all_six_expected_compiler_outcomes_are_counted(self):
        result, compiler = self.run_with(expected_compilation)
        self.assertEqual(compiler.call_count, 6)
        self.assertTrue(result["all_expected_outcomes_matched"])
        records = result["assessment"]["records"]
        self.assertEqual([row["case_id"] for row in records], [case["id"] for case in CASES])
        self.assertEqual([row["validator_expected_outcome_match"] for row in records], [1] * 6)
        self.assertEqual([row["projection_grammar_valid"] for row in records],
                         [case["grammar_valid"] for case in CASES])
        self.assertEqual([row["projection_reference_valid"] for row in records],
                         [1, None, 1, 0, 1, 1])
        self.assertEqual([row["structural_change_count"] for row in records],
                         [1, None, 0, None, 0, 0])
        self.assertEqual(result["assessment"]["metric_definition_version"], "boundary-v3")

    def test_unrelated_compiler_failure_does_not_pass_rejection_case(self):
        def unrelated_failure(case_request, case_result, **kwargs):
            if case_result["after_hc"] == CASES[1]["after_hc"]:
                raise PreviewError("Compiler preview exceeded its total deadline")
            return expected_compilation(case_request, case_result, **kwargs)
        result, compiler = self.run_with(unrelated_failure)
        self.assertEqual(compiler.call_count, 6)
        self.assertFalse(result["all_expected_outcomes_matched"])
        row = result["assessment"]["records"][1]
        self.assertEqual(row["case_id"], "case-002")
        self.assertEqual(row["validator_expected_outcome_match"], 0)
        self.assertIsNone(row["projection_grammar_valid"])
        self.assertIsNone(row["projection_reference_valid"])

    def test_generic_parse_failure_does_not_pass_syntax_rejection(self):
        def generic_parse_failure(case_request, case_result, **kwargs):
            if case_result["after_hc"] == CASES[1]["after_hc"]:
                raise CompilerCommandError("parse", 1, ())
            return expected_compilation(case_request, case_result, **kwargs)
        result, _ = self.run_with(generic_parse_failure)
        row = result["assessment"]["records"][1]
        self.assertFalse(result["all_expected_outcomes_matched"])
        self.assertEqual(row["validator_expected_outcome_match"], 0)
        self.assertIsNone(row["projection_grammar_valid"])
        self.assertIsNone(row["projection_reference_valid"])
        receipts = read_json(result["destination"] / "boundary-receipts.json")
        self.assertEqual(receipts[1]["compiler_failure"], {
            "operation": "parse", "return_code": 1, "diagnostic_codes": [],
        })

    def test_change_count_mismatch_keeps_successful_validity_metrics(self):
        def wrong_change_count(case_request, case_result, **kwargs):
            compiled = expected_compilation(case_request, case_result, **kwargs)
            if case_result["after_hc"] == CASES[0]["after_hc"]:
                return {"receipt": {"change_count": 9}}
            return compiled
        result, _ = self.run_with(wrong_change_count)
        row = result["assessment"]["records"][0]
        self.assertEqual(row["validator_expected_outcome_match"], 0)
        self.assertEqual(row["projection_grammar_valid"], 1)
        self.assertEqual(row["projection_reference_valid"], 1)
        self.assertEqual(row["structural_change_count"], 9)

    @unittest.skipUnless(os.environ.get("HYPERREVIEW_TEST_COMPILER"),
                         "set HYPERREVIEW_TEST_COMPILER to exercise the real compiler pilot")
    def test_real_compiler_pilot_matches_expected_outcomes(self):
        compiler = Path(os.environ["HYPERREVIEW_TEST_COMPILER"])
        result = run_pilot(compiler, hashlib.sha256(compiler.read_bytes()).hexdigest(),
                           self.output_root)
        self.assertTrue(result["all_expected_outcomes_matched"])
        records = result["assessment"]["records"]
        self.assertEqual([row["validator_expected_outcome_match"] for row in records], [1] * 6)
        self.assertEqual(records[1]["projection_grammar_valid"], 0)
        receipts = read_json(result["destination"] / "boundary-receipts.json")
        self.assertEqual(receipts[1]["compiler_failure"], {
            "operation": "parse", "return_code": 1, "diagnostic_codes": ["HC1001"],
        })

    def test_unchanged_case_six_is_accepted_without_behavior_proof(self):
        result, _ = self.run_with(expected_compilation)
        record = result["assessment"]["records"][5]
        self.assertEqual(record["case_id"], "case-006")
        self.assertEqual(record["validator_expected_outcome_match"], 1)
        self.assertEqual(record["structural_change_count"], 0)

        receipts = read_json(result["destination"] / "boundary-receipts.json")
        self.assertTrue(receipts[5]["accepted"])
        self.assertIsNone(receipts[5]["failure"])
        self.assertNotIn("behavior_verified", receipts[5])
        self.assertNotIn("behavior_preserved", receipts[5])

        worksheet = (result["destination"] / "reviewer-worksheet.md").read_text(encoding="utf-8")
        self.assertIn("not executed", worksheet)
        self.assertIn("Does an unchanged structural diff establish preserved approval?", worksheet)
        self.assertIn("fast", worksheet)
        self.assertIn("Human accuracy and review time are unmeasured.", worksheet)

    def test_worksheet_answer_key_and_unfilled_scorecard_are_separate(self):
        result, _ = self.run_with(expected_compilation)
        destination = result["destination"]
        worksheet = (destination / "reviewer-worksheet.md").read_text(encoding="utf-8")
        answer_key = (destination / "answer-key.md").read_text(encoding="utf-8")
        scorecard = (destination / "scorecard.csv").read_text(encoding="utf-8")
        self.assertNotEqual(worksheet, answer_key)
        for case in CASES:
            self.assertIn(case["question"], worksheet)
            self.assertNotIn(case["answer"], worksheet)
            self.assertIn(case["answer"], answer_key)
        parsed = list(csv.reader(scorecard.splitlines()))
        self.assertEqual(parsed[0], ["case_id", "reviewer_id", "condition", "order", "answer",
                                     "correct", "missed_violation", "review_seconds", "confidence"])
        self.assertEqual(len(parsed), 7)
        for row, case in zip(parsed[1:], CASES):
            self.assertEqual(len(row), 9)
            self.assertEqual(row[0], case["id"])
            self.assertEqual(row[1:], [""] * 8)

    def test_dataset_digest_is_stable_across_runs_and_independent_of_results(self):
        first, _ = self.run_with(expected_compilation)
        second_root = self.output_root.parent / "second"
        with mock.patch("hyperreview.pilot.compile_preview", side_effect=PreviewError("unrelated")):
            second = run_pilot("/different/compiler", "b" * 64, second_root)
        first_digest = first["assessment"]["dataset_digest"]
        second_digest = second["assessment"]["dataset_digest"]
        self.assertEqual(first_digest, second_digest)
        self.assertEqual(first_digest, intake.digest({
            "version": "controlled-boundaries-v2", "cases": CASES,
        }))
        first_dataset = read_json(first["destination"] / "dataset.json")
        second_dataset = read_json(second["destination"] / "dataset.json")
        self.assertEqual(first_dataset["dataset_digest"], first_digest)
        self.assertEqual(second_dataset["dataset_digest"], second_digest)


if __name__ == "__main__":
    unittest.main()
