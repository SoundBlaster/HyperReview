import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from hyperreview import intake, render
from hyperreview.feedback import FeedbackError, save_feedback
from hyperreview.model_contract import prepare_request
from hyperreview.storage import read_json
from test_model_contract import pack, source, valid_result


def make_bundle(path):
    path.mkdir(parents=True)
    evidence = pack([
        source("before", "old source\n", "src/before.py"),
        source("after", "new source\n", "src/after.py"),
    ])
    request = prepare_request(evidence)
    result = valid_result(request)
    result["before_hc"] = "Application\n"
    result["after_hc"] = "Application\n  Assessment\n"
    result["identity_map"] = [
        {"architecture_id": "#App", "before_role": "Application", "after_role": "Application",
         "before_refs": [item["id"] for item in request["sources"] if item["side"] == "before"],
         "after_refs": [item["id"] for item in request["sources"] if item["side"] == "after"],
         "reason": "The application remains the root."},
        {"architecture_id": "#Assessment", "before_role": None, "after_role": "Assessment",
         "before_refs": [],
         "after_refs": [item["id"] for item in request["sources"] if item["side"] == "after"],
         "reason": "Assessment responsibility is added."},
    ]
    bound = {"request_digest": request["request_digest"],
             "result_digest": intake.digest(result)}
    ir = {
        "before.ir.json": {"version": "hypercode.ir/v2", "nodes": []},
        "after.ir.json": {"version": "hypercode.ir/v2", "nodes": []},
    }
    diff = {"version": "hypercode.diff/v1", "changes": []}
    compiler = {
        **bound, "stage": "projections_validated", "compiler_sha256": "a" * 64,
        "before_resolver": {"name": "hypercode-swift", "version": "0.6.0-dev"},
        "after_resolver": {"name": "hypercode-swift", "version": "0.6.0-dev"},
        "before_ids": [], "after_ids": [],
        "change_count": 0, "elapsed_ms": 2,
    }
    for filename, document in [*ir.items(), ("diff.json", diff)]:
        raw = intake.encoded(document)
        (path / filename).write_bytes(raw)
        field = {"before.ir.json": "before_ir_sha256", "after.ir.json": "after_ir_sha256",
                 "diff.json": "diff_sha256"}[filename]
        compiler[field] = hashlib.sha256(raw).hexdigest()
    values = {
        "evidence.json": evidence,
        "request.json": request,
        "result.json": result,
        "compiler-receipt.json": compiler,
        "generation-receipt.json": {**bound, "stage": "model_generated", "provider": "lmstudio",
                                    "model": "fixture-model", "elapsed_ms": 1,
                                    "input_tokens": None, "output_tokens": None},
        "metadata.json": {**bound, "schema": "hyperreview.preview.v1",
                          "stage": "projections_validated", "tracking_correlation_id": str(uuid4()),
                          "delivery_mode": "preview", "attempt": 1},
    }
    for filename, value in values.items():
        (path / filename).write_bytes(intake.encoded(value))
    (path / "before.hc").write_text(result["before_hc"], encoding="utf-8")
    (path / "after.hc").write_text(result["after_hc"], encoding="utf-8")
    preview = render.render_compact_preview(request, result, compiler, diff)
    (path / "preview-compact.md").write_bytes(preview)
    (path / "preview.md").write_text("verbose fixture preview", encoding="utf-8")
    return request, result, compiler, diff, preview


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="hyperreview-feedback-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.bundle = self.root / "preview-bundle"
        self.request, self.result, self.compiler, self.diff, self.preview = make_bundle(self.bundle)
        self.output_root = self.root / "feedback"

    def test_saves_ok_and_not_ok_with_bound_provenance_and_optional_note(self):
        first = save_feedback(self.bundle, "ok", output_root=self.output_root,
                              expected_preview_sha256=hashlib.sha256(self.preview).hexdigest())
        second = save_feedback(self.bundle, "not_ok", note="Structure is unclear — please simplify.",
                               output_root=self.output_root)
        record = read_json(first / "feedback.json")
        self.assertEqual(record["schema"], "hyperreview.feedback.v1")
        self.assertEqual(record["assessment"], "ok")
        self.assertIsNone(record["note"])
        self.assertEqual(record["repository"], self.request["repository"])
        self.assertEqual(record["pr"], self.request["pr"])
        self.assertEqual(record["merge_base_sha"], self.request["merge_base_sha"])
        self.assertEqual(record["head_sha"], self.request["head_sha"])
        self.assertEqual(record["request_digest"], self.request["request_digest"])
        self.assertEqual(record["result_digest"], intake.digest(self.result))
        self.assertEqual(record["projection_digest"], intake.digest({
            "before_hc": self.result["before_hc"], "after_hc": self.result["after_hc"]}))
        self.assertEqual(record["preview_sha256"], hashlib.sha256(self.preview).hexdigest())
        self.assertEqual(record["prompt_version"], self.request["prompt_version"])
        self.assertEqual(record["abstraction_profile"], self.request["abstraction_profile"])
        self.assertEqual(record["render_version"], render.COMPACT_RENDER_VERSION)
        self.assertEqual(record["compiler_sha256"], self.compiler["compiler_sha256"])
        self.assertTrue(record["tracking_correlation_id"])
        self.assertEqual(record["created_at"][-1], "Z")
        self.assertEqual(record["assessment"], "ok")
        noted = read_json(second / "feedback.json")
        self.assertEqual(noted["assessment"], "not_ok")
        self.assertEqual(noted["note"], "Structure is unclear — please simplify.")
        self.assertNotEqual(first, second)
        self.assertEqual((first / "feedback.json").stat().st_mode & 0o777, 0o600)

    def test_rejects_invalid_assessment_note_hash_and_bundle_paths(self):
        invalid_inputs = [
            ("maybe", None, None, self.bundle),
            ("ok", "x" * 2001, None, self.bundle),
            ("ok", "contains\x00nul", None, self.bundle),
            ("ok", "\ud800", None, self.bundle),
            ("ok", None, "A" * 64, self.bundle),
            ("ok", None, None, Path("relative-bundle")),
            ("ok", None, None, self.root / ".." / "preview-bundle"),
        ]
        for assessment, note, digest, bundle in invalid_inputs:
            with self.subTest(assessment=assessment, note=repr(note)[:20], bundle=bundle):
                with self.assertRaises(FeedbackError):
                    save_feedback(bundle, assessment, note=note, expected_preview_sha256=digest,
                                  output_root=self.output_root)
        link = self.root / "bundle-link"
        link.symlink_to(self.bundle, target_is_directory=True)
        with self.assertRaises(FeedbackError):
            save_feedback(link, "ok", output_root=self.output_root)
        with self.assertRaises(FeedbackError):
            save_feedback(self.bundle, "ok", output_root=self.bundle / "feedback")
        with self.assertRaises(FeedbackError):
            save_feedback(self.bundle, "ok", output_root=self.root / ".." / "feedback")

    def test_rejects_stale_compact_preview_hash(self):
        with self.assertRaises(FeedbackError) as raised:
            save_feedback(self.bundle, "ok", note="private feedback note",
                          expected_preview_sha256="0" * 64, output_root=self.output_root)
        self.assertNotIn("private feedback note", str(raised.exception))
        self.assertFalse(self.output_root.exists())

    def test_rejects_tampered_preview_result_or_compiled_artifact(self):
        cases = ("preview-compact.md", "result.json", "after.ir.json")
        for filename in cases:
            with self.subTest(filename=filename):
                other = self.root / ("tampered-" + filename.replace(".", "-"))
                request, result, compiler, diff, preview = make_bundle(other)
                if filename == "preview-compact.md":
                    (other / filename).write_bytes(preview + b"tampered")
                elif filename == "result.json":
                    changed = json.loads((other / filename).read_text())
                    changed["summary"] = "different result"
                    (other / filename).write_bytes(intake.encoded(changed))
                else:
                    (other / filename).write_bytes(b"tampered IR")
                with self.assertRaises(FeedbackError):
                    save_feedback(other, "ok", output_root=self.output_root)

    def test_rejects_symlinked_compact_preview(self):
        preview = self.bundle / "preview-compact.md"
        preview.unlink()
        preview.symlink_to(self.root / "outside-preview.md")
        with self.assertRaises(FeedbackError):
            save_feedback(self.bundle, "ok", output_root=self.output_root)

    def test_accepts_pretty_printed_diff_when_receipt_fingerprints_raw_bytes(self):
        diff_path = self.bundle / "diff.json"
        compiler_path = self.bundle / "compiler-receipt.json"
        diff = json.loads(diff_path.read_text(encoding="utf-8"))
        raw_diff = json.dumps(diff, indent=2, ensure_ascii=False).encode("utf-8")
        diff_path.write_bytes(raw_diff)
        compiler = json.loads(compiler_path.read_text(encoding="utf-8"))
        compiler["diff_sha256"] = hashlib.sha256(raw_diff).hexdigest()
        compiler_path.write_bytes(intake.encoded(compiler))

        destination = save_feedback(self.bundle, "ok", output_root=self.output_root)

        self.assertEqual(read_json(destination / "feedback.json")["assessment"], "ok")

    @unittest.skipUnless(hasattr(os, "mkfifo"), "named pipes are unavailable")
    def test_rejects_fifo_compact_preview_without_blocking(self):
        preview = self.bundle / "preview-compact.md"
        preview.unlink()
        os.mkfifo(preview)
        with self.assertRaises(FeedbackError):
            save_feedback(self.bundle, "ok", output_root=self.output_root)

    def test_append_only_does_not_mutate_preview_bundle(self):
        before = {path.name: (path.read_bytes(), path.stat().st_mode & 0o777)
                  for path in self.bundle.iterdir() if path.is_file()}
        first = save_feedback(self.bundle, "ok", output_root=self.output_root)
        second = save_feedback(self.bundle, "not_ok", note="Please revisit.",
                               output_root=self.output_root)
        after = {path.name: (path.read_bytes(), path.stat().st_mode & 0o777)
                 for path in self.bundle.iterdir() if path.is_file()}
        self.assertEqual(after, before)
        self.assertEqual(len(list(self.output_root.iterdir())), 2)
        self.assertTrue((first / "feedback.json").is_file())
        self.assertTrue((second / "feedback.json").is_file())


if __name__ == "__main__":
    unittest.main()
