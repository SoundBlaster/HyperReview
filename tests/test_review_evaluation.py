import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from hyperreview import intake, review_evaluation as evaluation, review_evaluation_sdk as sdk


class ReviewEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.suite = {
            "schema": evaluation.SUITE_SCHEMA, "version": "fixture-v1", "cases": [{
                "id": "case-001", "repository": "0al-spec/SpecGraph", "pr": 1,
                "base": "a" * 40, "head": "b" * 40,
                "checks": [
                    {"id": "check-001", "kind": "source", "side": "after", "path": "store.py"},
                    {"id": "check-002", "kind": "relation", "side": "after", "relation_kind": "calls",
                     "from_contains": ["Store", "update"], "to_contains": ["publish"]},
                    {"id": "check-003", "kind": "containment", "side": "after", "roles": ["App", "Store"]},
                ], "rubric": ["Private human rubric, never sent to SDKs"]}]}
        self.baseline = self.bundle("baseline", profile="a", calls=True)
        self.candidate = self.bundle("candidate", profile="b", calls=False)
        self.pairs = {"schema": evaluation.PAIR_SCHEMA, "suite_digest": intake.digest(self.suite), "pairs": [{
            "case_id": "case-001", "axis": "explanation", "baseline": str(self.baseline),
            "candidate": str(self.candidate), "baseline_digest": evaluation.bundle_digest(self.baseline, axis="explanation"),
            "candidate_digest": evaluation.bundle_digest(self.candidate, axis="explanation")}]}

    def bundle(self, name, *, profile, calls):
        directory = self.root / name
        directory.mkdir(mode=0o700)
        evidence = {"limits": {"evidence_bytes": 262144}}
        evidence["evidence_digest"] = intake.digest(evidence)
        content = "PRIVATE_SOURCE_CONTENT\n"
        source = {"content": content, "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
                  "path": "store.py", "side": "after", "revision": "b" * 40}
        request = {"repository": "0al-spec/SpecGraph", "pr": 1, "merge_base_sha": "a" * 40,
                   "head_sha": "b" * 40, "evidence_digest": evidence["evidence_digest"], "sources": [source],
                   "reviewer_profile": {"sha256": profile * 64, "version": "fixture-" + profile},
                   "prompt_version": "fixture-" + profile,
                   "source_selection": {"mode": "all", "include_paths": None, "max_source_bytes": 262144}}
        request["request_digest"] = intake.digest(request)
        result = {"request_digest": request["request_digest"], "before_hc": "App\n  Store\n",
                  "after_hc": "App\n  Store\n", "claims": [{
                      "id": "relation-v2-calls-1", "scope": "После; source analysis",
                      "text": "Store.update → Store.publish"}] if calls else []}
        ir = b'{"fixture":true}'
        receipt = {"request_digest": request["request_digest"], "result_digest": intake.digest(result),
                   "stage": "projections_validated", "compiler_sha256": "c" * 64,
                   **{f"{side}_ir_sha256": hashlib.sha256(ir).hexdigest() for side in ("before", "after")}}
        generation = {"request_digest": request["request_digest"], "result_digest": intake.digest(result),
                      "provider": "fixture", "model": "fixture", "reasoning_effort": "medium",
                      "executable_sha256": "d" * 64, "prompt_version": request["prompt_version"],
                      "reviewer_profile_sha256": request["reviewer_profile"]["sha256"]}
        for filename, value in (("request", request), ("evidence", evidence), ("result", result),
                                ("compiler-receipt", receipt), ("generation-receipt", generation)):
            (directory / f"{filename}.json").write_bytes(intake.encoded(value))
        for side in ("before", "after"):
            (directory / f"{side}.hc").write_text(result[f"{side}_hc"])
            (directory / f"{side}.ir.json").write_bytes(ir)
        return directory

    def change_json(self, path, edit, *, redigest=None):
        value = json.loads(path.read_text())
        edit(value)
        if redigest:
            value.pop(redigest)
            value[redigest] = intake.digest(value)
        path.write_bytes(intake.encoded(value))

    def reseal_candidate(self, axis="explanation"):
        self.pairs["pairs"][0]["candidate_digest"] = evaluation.bundle_digest(self.candidate, axis=axis)

    def test_numeric_witnesses_report_regression_without_semantic_verdict(self):
        report = evaluation.compare(self.suite, self.pairs)
        self.assertTrue(report["checks"][1]["regressed"])
        self.assertEqual(report["rows"][0]["outputs"]["relation_presence"], 1)
        self.assertEqual(report["rows"][1]["outputs"]["relation_presence"], 0)
        self.assertEqual(report["rows"][1]["outputs"]["containment_preserved"], 1)
        self.assertEqual(report["semantic_assessment"], "pending")
        self.assertFalse(report["publication_gate"])

    def test_intake_does_not_count_unmeasured_relations_as_pass_or_fail(self):
        # Same profile/prompt required; projection artifacts are not needed.
        self.pairs["pairs"][0].update(axis="intake", candidate=str(self.baseline))
        for variant in ("baseline", "candidate"):
            self.pairs["pairs"][0][f"{variant}_digest"] = evaluation.bundle_digest(self.baseline, axis="intake")
        report = evaluation.compare(self.suite, self.pairs)
        self.assertIsNone(report["rows"][0]["outputs"]["relation_presence"])
        self.assertIsNone(report["rows"][0]["outputs"]["compiler_receipt_consistent"])
        self.assertIsNone(report["checks"][1]["candidate"])

    def test_sealed_artifact_mutation_is_rejected(self):
        self.change_json(self.candidate / "generation-receipt.json", lambda v: v.update(model="changed"))
        with self.assertRaisesRegex(evaluation.ReviewEvaluationError, "Sealed artifact"):
            evaluation.compare(self.suite, self.pairs)

    def test_model_change_is_not_a_prompt_comparison(self):
        self.change_json(self.candidate / "generation-receipt.json", lambda v: v.update(model="changed"))
        self.reseal_candidate()
        with self.assertRaisesRegex(evaluation.ReviewEvaluationError, "provider/model"):
            evaluation.compare(self.suite, self.pairs)

    def test_source_selection_change_is_not_a_prompt_comparison(self):
        self.change_json(self.candidate / "request.json", lambda v: v["source_selection"].update(max_source_bytes=100),
                         redigest="request_digest")
        request = json.loads((self.candidate / "request.json").read_text())
        for file in ("result", "compiler-receipt", "generation-receipt"):
            self.change_json(self.candidate / f"{file}.json", lambda v: v.update(request_digest=request["request_digest"]))
        result_digest = intake.digest(json.loads((self.candidate / "result.json").read_text()))
        for file in ("compiler-receipt", "generation-receipt"):
            self.change_json(self.candidate / f"{file}.json", lambda v: v.update(result_digest=result_digest))
        self.reseal_candidate()
        with self.assertRaisesRegex(evaluation.ReviewEvaluationError, "identical frozen inputs"):
            evaluation.compare(self.suite, self.pairs)

    def test_ir_and_projection_tampering_are_rejected(self):
        for name in ("after.ir.json", "after.hc"):
            with self.subTest(name=name):
                file = self.candidate / name
                original = file.read_bytes()
                file.write_bytes(original + b" ")
                with self.assertRaises(evaluation.ReviewEvaluationError):
                    self.reseal_candidate()
                file.write_bytes(original)

    def test_sdk_seam_receives_no_source_paths_prose_or_local_rubric(self):
        received = []
        sdk.evaluate(self.suite, self.pairs, database=self.root / "tracking.sqlite",
                     artifacts_root=self.root / "artifacts", output_root=self.root / "reports",
                     engine=lambda report, **kwargs: received.append(report))
        serialized = intake.encoded(received).decode()
        for private in ("PRIVATE_SOURCE_CONTENT", "Private human rubric", "store.py", str(self.candidate), "Store.update"):
            self.assertNotIn(private, serialized)

    def test_invalid_lineage_never_calls_sdk(self):
        self.pairs["suite_digest"] = "0" * 64
        with self.assertRaises(evaluation.ReviewEvaluationError):
            sdk.evaluate(self.suite, self.pairs, database=self.root / "tracking.sqlite",
                         artifacts_root=self.root / "artifacts", output_root=self.root / "reports",
                         engine=lambda *a, **kw: self.fail("SDK called"))

    def test_suite_rejects_duplicate_ids_sensitive_paths_and_unknown_checks(self):
        for change in (lambda s: s["cases"].append(copy.deepcopy(s["cases"][0])),
                       lambda s: s["cases"][0]["checks"][0].update(path="secret.py"),
                       lambda s: s["cases"][0]["checks"][0].update(kind="judge")):
            suite = copy.deepcopy(self.suite)
            change(suite)
            with self.assertRaises(evaluation.ReviewEvaluationError):
                evaluation.validate_suite(suite)

    def test_checked_in_suite_is_valid_and_pinned(self):
        for version in ("v1", "v2", "v3", "v4"):
            suite = json.loads((Path(__file__).resolve().parents[1] / f"evaluations/reviewer-{version}.json").read_text())
            evaluation.validate_suite(suite)
            self.assertEqual(len(suite["cases"]), 4 if version == "v4" else 3)

    def test_exact_relation_does_not_reward_compound_or_guessed_targets(self):
        case = copy.deepcopy(self.suite["cases"][0])
        case["checks"] = [{"id": "check-001", "kind": "relation_exact", "side": "after",
                           "relation_kind": "calls", "from_any": ["Reader.read"],
                           "to_any": ["snapshot", "self.snapshot"]}]
        bundle = evaluation.load_bundle(self.baseline, projection=True)
        for target, expected in (("snapshot", 1), ("self.snapshot", 1), ("Store.snapshot", 0),
                                 ("snapshot and Store.latestID", 0), ("snapshot, latestID", 0)):
            with self.subTest(target=target):
                bundle["result"]["claims"][0]["text"] = f"Reader.read → {target}"
                values, checks = evaluation.observe(case, bundle, "explanation")
                self.assertEqual(values["relation_presence"], expected)
                self.assertEqual(checks[0]["value"], expected)
        bundle["result"]["claims"][0]["text"] = "Reader.read and Writer.write → snapshot"
        self.assertEqual(evaluation.observe(case, bundle, "explanation")[0]["relation_presence"], 0)

    def test_exact_relation_schema_stays_bounded_and_unmeasured_on_intake(self):
        case = self.suite["cases"][0]
        check = {"id": "check-004", "kind": "relation_exact", "side": "after", "relation_kind": "calls",
                 "from_any": ["Store.read"], "to_any": ["snapshot", "self.snapshot"]}
        case["checks"].append(check)
        evaluation.validate_suite(self.suite)
        values, checks = evaluation.observe(case, evaluation.load_bundle(self.baseline, projection=False), "intake")
        self.assertIsNone(values["relation_presence"])
        self.assertIsNone(checks[-1]["value"])
        for field, bad in (("from_any", []), ("to_any", ["snapshot"] * 9), ("to_any", "snapshot")):
            suite = copy.deepcopy(self.suite)
            suite["cases"][0]["checks"][-1][field] = bad
            with self.assertRaises(evaluation.ReviewEvaluationError):
                evaluation.validate_suite(suite)

    def test_forbidden_relation_is_separate_from_positive_coverage(self):
        forbidden = copy.deepcopy(self.suite["cases"][0]["checks"][1])
        forbidden.update(id="check-004", kind="relation_absence")
        self.suite["cases"][0]["checks"].append(forbidden)
        self.pairs["suite_digest"] = intake.digest(self.suite)
        report = evaluation.compare(self.suite, self.pairs)
        self.assertEqual(report["rows"][0]["outputs"]["forbidden_relation_absent"], 0)
        self.assertEqual(report["rows"][1]["outputs"]["forbidden_relation_absent"], 1)
        # An empty relation list also fails the positive witness. No aggregate
        # score can hide that missing coverage behind forbidden-edge absence.
        self.assertEqual(report["rows"][1]["outputs"]["relation_presence"], 0)
        self.assertEqual(report["rows"][1]["outputs"]["compiler_receipt_consistent"], 1)

    def test_forbidden_relation_is_unmeasured_without_projection(self):
        case = copy.deepcopy(self.suite["cases"][0])
        case["checks"][1]["kind"] = "relation_absence"
        bundle = evaluation.load_bundle(self.baseline, projection=False)
        values, checks = evaluation.observe(case, bundle, "intake")
        self.assertIsNone(values["forbidden_relation_absent"])
        self.assertIsNone(checks[1]["value"])

    def test_incomplete_suite_coverage_remains_visible(self):
        other = copy.deepcopy(self.suite["cases"][0])
        other["id"] = "case-002"
        self.suite["cases"].append(other)
        self.pairs["suite_digest"] = intake.digest(self.suite)
        report = evaluation.compare(self.suite, self.pairs)
        self.assertEqual(report["coverage"]["explanation"]["unpaired_cases"], ["case-002"])

    def test_native_aggregate_verification_accepts_numeric_scalars_only(self):
        class Scalar(float):
            pass
        self.assertTrue(sdk._mean_matches(Scalar(0.5), 0.5))
        for value in (None, "0.5", True, float("nan"), float("inf"), 0.7):
            self.assertFalse(sdk._mean_matches(value, 0.5))


if __name__ == "__main__":
    unittest.main()
