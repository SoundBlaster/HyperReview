import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from hyperreview import intake, model_contract
from hyperreview.compiled_preview import CompilerCommandError, PreviewError, compile_preview


REPO = "0al-spec/SpecGraph"
BASE = "a" * 40
HEAD = "b" * 40


def source(side, text, revision):
    raw = text.encode("utf-8")
    return {
        "side": side, "revision": revision, "path": "src/application.py",
        "content": text, "content_sha256": hashlib.sha256(raw).hexdigest(),
        "content_bytes": len(raw), "line_start": 1,
        "line_end": text.count("\n") + int(not text.endswith("\n")),
        "trust": "untrusted_source_data", "url": "https://example.invalid/source",
    }


def make_request(*, include_before=True):
    sources = []
    if include_before:
        sources.append(source("before", "before evidence\n", BASE))
    sources.append(source("after", "after evidence\n", HEAD))
    evidence = {
        "schema": intake.SCHEMA, "stage": "evidence_collected",
        "repository": REPO, "pr": 59, "author": intake.AUTHOR,
        "authenticated_account": intake.AUTHOR, "base_repo": REPO, "head_repo": REPO,
        "state": "open", "draft": False, "base_sha": "c" * 40,
        "merge_base_sha": BASE, "head_sha": HEAD,
        "files": [{"before_path": "src/application.py" if include_before else None,
                    "after_path": "src/application.py", "sources": sources, "omissions": []}],
    }
    evidence["evidence_digest"] = intake.digest(evidence)
    return model_contract.prepare_request(evidence)


def make_result(request, *, before_hc="Application#App\n", after_hc="Application#App\n"):
    before_refs = [source["id"] for source in request["sources"] if source["side"] == "before"]
    after_refs = [source["id"] for source in request["sources"] if source["side"] == "after"]
    refs = before_refs + after_refs
    return {
        "schema": model_contract.RESULT_SCHEMA,
        "request_digest": request["request_digest"],
        "before_hc": before_hc,
        "after_hc": after_hc,
        "identity_map": [{"architecture_id": "#App", "before_refs": before_refs,
                          "after_refs": after_refs, "reason": "The same responsibility remains."}],
        "claims": [{"id": "claim-app", "text": "The application responsibility remains.",
                    "evidence_status": "inferred", "architecture_ids": ["#App"],
                    "source_refs": refs, "scope": "Supplied source only.",
                    "limitations": ["Responsibility is inferred."]}],
        "summary": "One application responsibility is proposed.",
        "limitations": ["The compiler checks syntax, not semantic correctness."],
    }


def ir_node(identifier="App", node_hash="a" * 64):
    return {"type": "Application", "id": identifier, "hash": node_hash,
            "properties": {}, "children": []}


def ir_document(nodes=None):
    return {"version": "hypercode.ir/v2", "context": {},
            "resolver": {"name": "hypercode-swift", "version": "test"},
            "documentHash": "c" * 64,
            "nodes": [ir_node()] if nodes is None else nodes}


class FakeCompiler:
    def __init__(self, root, mode="changed", *, before=None, after=None):
        self.path = root / f"hypercode-{mode}"
        self.before = ir_document() if before is None else before
        self.after = ir_document([ir_node(node_hash="b" * 64)]) if after is None else after
        self.mode = mode
        self._write()

    def _write(self):
        script = f'''#!{sys.executable}
import json, pathlib, sys, time
MODE = {self.mode!r}
BEFORE = json.loads({json.dumps(json.dumps(self.before))})
AFTER = json.loads({json.dumps(json.dumps(self.after))})
args = sys.argv[1:]
if args[:2] == ["--diagnostics", "json"]: args = args[2:]
command = args[0]
if MODE == "timeout" and command == "parse":
    time.sleep(10)
if MODE == "orphan_pipe" and command == "parse":
    import subprocess
    subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
if MODE == "tamper" and command == "parse":
    pathlib.Path(sys.argv[0]).write_bytes(b"changed executable")
if MODE == "stdout_limit" and command == "parse":
    sys.stdout.write("x" * (1024 * 1024 + 10)); sys.stdout.flush()
if MODE == "stderr_limit" and command == "parse":
    sys.stderr.write("x" * (1024 * 1024 + 10)); sys.stderr.flush()
if MODE == "fail_validate" and command == "validate":
    sys.stderr.write("PRIVATE DIAGNOSTIC CONTENT")
    sys.exit(2)
if MODE == "fail_parse" and command == "parse":
    sys.stderr.write("PRIVATE COMPILER FAILURE")
    sys.exit(1)
if MODE == "syntax_error" and command == "parse":
    sys.stderr.write(json.dumps([{{"code": "HC1001", "severity": 1, "source": "hypercode", "message": "PRIVATE MESSAGE", "file": "/private/path"}}]))
    sys.exit(1)
if MODE == "mixed_syntax_error" and command == "parse":
    sys.stderr.write(json.dumps([{{"code": "HC1001", "severity": 1, "source": "hypercode"}},
                                 {{"code": "HC9999", "severity": 1, "source": "hypercode"}}]))
    sys.exit(1)
if command in ("parse", "validate"):
    print("ok")
elif command == "emit":
    source = pathlib.Path(args[1])
    value = BEFORE if source.name == "before.hc" else AFTER
    if MODE == "invalid_ir": value = {{"version": "wrong", "nodes": []}}
    if MODE == "duplicate_ids": value = dict(value); value["nodes"] = [{{"type": "A", "id": "App", "hash": "a"*64, "properties": {{}}, "children": []}}, {{"type": "B", "id": "App", "hash": "b"*64, "properties": {{}}, "children": []}}]
    if MODE == "nonstring_id": value = dict(value); value["nodes"] = [{{"type": "A", "id": 2, "hash": "a"*64, "properties": {{}}, "children": []}}]
    if MODE == "node_extra": value = dict(value); value["nodes"] = [{{"type": "A", "hash": "a"*64, "properties": {{}}, "children": [], "extra": True}}]
    sys.stdout.write(json.dumps(value))
elif command == "diff":
    changes = [] if MODE == "identical" else [{{"kind": "modified", "node": "Application#App"}}]
    if MODE == "diff_invalid": print(json.dumps({{"version": "bad", "changes": changes}})); sys.exit(1 if changes else 0)
    if MODE == "diff_mismatch": changes = []; print(json.dumps({{"version": "hypercode.diff/v1", "changes": changes}})); sys.exit(1)
    if MODE == "diff_exit_mismatch": print(json.dumps({{"version": "hypercode.diff/v1", "changes": changes}})); sys.exit(0)
    if MODE == "diff_failure": print(json.dumps({{"version": "hypercode.diff/v1", "changes": changes}})); sys.exit(2)
    print(json.dumps({{"version": "hypercode.diff/v1", "changes": changes}}))
    sys.exit(1 if changes else 0)
'''
        self.path.write_text(script, encoding="utf-8")
        self.path.chmod(0o700)

    @property
    def digest(self):
        return hashlib.sha256(self.path.read_bytes()).hexdigest()


class CompiledPreviewTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="compiled-preview-test-")
        self.root = Path(self.folder.name)
        self.request = make_request()
        self.result = make_result(self.request)

    def tearDown(self):
        self.folder.cleanup()

    def compiler(self, mode="changed", **kwargs):
        fake = FakeCompiler(self.root, mode, **kwargs)
        return fake.path, fake.digest

    def compile(self, *, mode="changed", request=None, result=None, timeout_seconds=60, **kwargs):
        compiler, digest = self.compiler(mode, **kwargs)
        return compile_preview(request or self.request, result or self.result,
                              compiler=compiler, compiler_sha256=digest,
                              timeout_seconds=timeout_seconds)

    def test_success_returns_bundle_bytes_and_sanitized_receipt(self):
        output = self.compile()
        artifacts = output["artifacts"]
        self.assertEqual(set(artifacts), {
            "before.hc", "after.hc", "before.ir.json", "after.ir.json", "diff.json",
            "result.json", "request.json", "compiler-receipt.json",
        })
        self.assertTrue(all(type(body) is bytes for body in artifacts.values()))
        receipt = output["receipt"]
        self.assertEqual(receipt["stage"], "projections_validated")
        self.assertEqual(receipt["request_digest"], self.request["request_digest"])
        self.assertEqual(receipt["result_digest"], intake.digest(self.result))
        self.assertEqual(receipt["before_ids"], ["App"])
        self.assertEqual(receipt["after_ids"], ["App"])
        self.assertEqual(receipt["change_count"], 1)
        self.assertEqual(receipt["evidence_status"], "inferred")
        self.assertEqual(receipt["tracking_status"], "not_started")
        for sensitive in ("The same responsibility", "after evidence", "Application#App"):
            self.assertNotIn(sensitive, json.dumps(receipt))
        self.assertEqual(json.loads(artifacts["compiler-receipt.json"]), receipt)
        self.assertEqual(hashlib.sha256(artifacts["before.ir.json"]).hexdigest(),
                         receipt["before_ir_sha256"])
        self.assertEqual(hashlib.sha256(artifacts["diff.json"]).hexdigest(),
                         receipt["diff_sha256"])
        before_ir = json.loads(artifacts["before.ir.json"])
        after_ir = json.loads(artifacts["after.ir.json"])
        self.assertEqual(receipt["before_document_hash"], before_ir["documentHash"])
        self.assertEqual(receipt["after_document_hash"], after_ir["documentHash"])
        self.assertEqual(receipt["before_resolver"], before_ir["resolver"])
        self.assertEqual(receipt["after_resolver"], after_ir["resolver"])

    def test_identical_diff_requires_exit_zero(self):
        output = self.compile(mode="identical")
        self.assertEqual(output["receipt"]["change_count"], 0)
        self.assertEqual(json.loads(output["artifacts"]["diff.json"])["changes"], [])

    def test_rejects_actual_id_map_mismatch(self):
        wrong = make_result(self.request)
        wrong["identity_map"][0]["architecture_id"] = "#Specification"
        wrong["claims"][0]["architecture_ids"] = ["#Specification"]
        compiler, digest = self.compiler()
        with self.assertRaisesRegex(PreviewError, "IR IDs do not match"):
            compile_preview(self.request, wrong, compiler=compiler, compiler_sha256=digest)

    def test_rejects_missing_side_reference_and_fabricated_before_baseline(self):
        missing_before = make_result(self.request)
        missing_before["identity_map"][0]["before_refs"] = []
        compiler, digest = self.compiler()
        with self.assertRaisesRegex(PreviewError, "Before-side identity references"):
            compile_preview(self.request, missing_before, compiler=compiler, compiler_sha256=digest)

        added_request = make_request(include_before=False)
        added_result = make_result(added_request, before_hc="\n")
        compiler, digest = self.compiler()
        with self.assertRaisesRegex(PreviewError, "Before-side identity references"):
            compile_preview(added_request, added_result, compiler=compiler, compiler_sha256=digest)

    def test_added_node_can_use_empty_before_ir_and_newline_source(self):
        request = make_request(include_before=False)
        result = make_result(request, before_hc="\n")
        result["identity_map"][0]["architecture_id"] = "#Assessment"
        result["identity_map"][0]["before_refs"] = []
        result["identity_map"][0]["after_refs"] = [
            source["id"] for source in request["sources"] if source["side"] == "after"
        ]
        result["claims"][0]["architecture_ids"] = ["#Assessment"]
        compiler, digest = self.compiler(
            before=ir_document([]), after=ir_document([ir_node("Assessment")]),
        )
        preview = compile_preview(request, result, compiler=compiler, compiler_sha256=digest)
        self.assertEqual(preview["receipt"]["before_ids"], [])
        self.assertEqual(preview["receipt"]["after_ids"], ["Assessment"])
        self.assertEqual(preview["artifacts"]["before.hc"], b"\n")

    def test_rejects_unmapped_or_duplicate_ir_ids_and_invalid_shapes(self):
        invalids = (
            ("extra-id", {"after": ir_document([ir_node("App"), ir_node("Extra", "d" * 64)])}),
            ("duplicate_ids", {}),
            ("nonstring_id", {}),
            ("node_extra", {}),
            ("invalid_ir", {}),
        )
        for mode, arguments in invalids:
            with self.subTest(mode=mode):
                compiler, digest = self.compiler(mode, **arguments)
                with self.assertRaises(PreviewError):
                    compile_preview(self.request, self.result, compiler=compiler, compiler_sha256=digest)

    def test_diff_schema_and_exit_code_must_agree(self):
        for mode in ("diff_invalid", "diff_mismatch", "diff_exit_mismatch", "diff_failure"):
            with self.subTest(mode=mode):
                compiler, digest = self.compiler(mode)
                with self.assertRaises(PreviewError):
                    compile_preview(self.request, self.result, compiler=compiler, compiler_sha256=digest)

    def test_compile_failure_diagnostics_are_not_returned(self):
        compiler, digest = self.compiler("fail_validate")
        with self.assertRaises(CompilerCommandError) as caught:
            compile_preview(self.request, self.result, compiler=compiler, compiler_sha256=digest)
        self.assertNotIn("PRIVATE DIAGNOSTIC CONTENT", str(caught.exception))
        self.assertEqual(caught.exception.operation, "validate")
        self.assertEqual(caught.exception.return_code, 2)
        self.assertEqual(caught.exception.diagnostic_codes, ())
        self.assertNotIn("PRIVATE", repr(caught.exception.__dict__))

    def test_parse_failure_exposes_only_allowlisted_diagnostic_codes(self):
        compiler, digest = self.compiler("syntax_error")
        with self.assertRaises(CompilerCommandError) as caught:
            compile_preview(self.request, self.result, compiler=compiler, compiler_sha256=digest)
        self.assertEqual(str(caught.exception), "Hypercode compiler command failed")
        self.assertEqual(caught.exception.operation, "parse")
        self.assertEqual(caught.exception.return_code, 1)
        self.assertEqual(caught.exception.diagnostic_codes, ("HC1001",))
        self.assertNotIn("PRIVATE", repr(caught.exception.__dict__))

    def test_unstructured_parse_failure_has_no_diagnostic_identity(self):
        compiler, digest = self.compiler("fail_parse")
        with self.assertRaises(CompilerCommandError) as caught:
            compile_preview(self.request, self.result, compiler=compiler, compiler_sha256=digest)
        self.assertEqual(caught.exception.operation, "parse")
        self.assertEqual(caught.exception.return_code, 1)
        self.assertEqual(caught.exception.diagnostic_codes, ())

    def test_mixed_parse_diagnostics_cannot_match_allowlisted_rejection(self):
        compiler, digest = self.compiler("mixed_syntax_error")
        with self.assertRaises(CompilerCommandError) as caught:
            compile_preview(self.request, self.result, compiler=compiler, compiler_sha256=digest)
        self.assertEqual(caught.exception.diagnostic_codes, ())

    def test_compiler_hash_is_checked_before_and_after_each_call(self):
        compiler, digest = self.compiler("tamper")
        with self.assertRaisesRegex(PreviewError, "SHA256"):
            compile_preview(self.request, self.result, compiler=compiler, compiler_sha256=digest)
        with self.assertRaisesRegex(PreviewError, "SHA256"):
            compile_preview(self.request, self.result, compiler=compiler, compiler_sha256=digest)

    def test_original_path_replacement_after_copy_never_runs_substitute(self):
        compiler, digest = self.compiler()
        marker = self.root / "substitute-ran"
        replacement = self.root / "replacement-compiler"
        replacement.write_text(
            f"#!{sys.executable}\nfrom pathlib import Path\n"
            f"Path({str(marker)!r}).write_text('executed')\n",
            encoding="utf-8",
        )
        replacement.chmod(0o700)
        real_popen = subprocess.Popen
        did_replace = False

        def replace_original_then_spawn(arguments, *args, **kwargs):
            nonlocal did_replace
            if not did_replace:
                os.replace(replacement, compiler)
                did_replace = True
            return real_popen(arguments, *args, **kwargs)

        with mock.patch("hyperreview.compiled_preview.subprocess.Popen",
                        side_effect=replace_original_then_spawn):
            preview = compile_preview(self.request, self.result, compiler=compiler,
                                      compiler_sha256=digest)
        self.assertTrue(did_replace)
        self.assertEqual(preview["receipt"]["compiler_sha256"], digest)
        self.assertFalse(marker.exists())

    def test_rejects_symlink_nonexecutable_relative_and_wrong_digest(self):
        compiler, digest = self.compiler()
        link = self.root / "compiler-link"
        link.symlink_to(compiler)
        cases = ((link, digest), (compiler, "0" * 64), (Path("relative/compiler"), digest))
        for path, expected in cases:
            with self.subTest(path=path), self.assertRaises(PreviewError):
                compile_preview(self.request, self.result, compiler=path, compiler_sha256=expected)
        compiler.chmod(0o600)
        with self.assertRaisesRegex(PreviewError, "not executable"):
            compile_preview(self.request, self.result, compiler=compiler, compiler_sha256=digest)

    def test_subprocess_output_has_a_combined_one_mib_cap(self):
        for mode in ("stdout_limit", "stderr_limit"):
            with self.subTest(mode=mode):
                compiler, digest = self.compiler(mode)
                with self.assertRaisesRegex(PreviewError, "output exceeds 1 MiB"):
                    compile_preview(self.request, self.result, compiler=compiler,
                                    compiler_sha256=digest)

    def test_aggregate_timeout_terminates_and_reaps_compiler(self):
        compiler, digest = self.compiler("timeout")
        with self.assertRaisesRegex(PreviewError, "total deadline"):
            compile_preview(self.request, self.result, compiler=compiler,
                            compiler_sha256=digest, timeout_seconds=1)

    @unittest.skipUnless(os.name == "posix", "process groups are POSIX-specific")
    def test_exits_when_descendant_keeps_compiler_output_pipe_open(self):
        compiler, digest = self.compiler("orphan_pipe")
        started = time.monotonic()
        with self.assertRaisesRegex(PreviewError, "output stream did not close"):
            compile_preview(self.request, self.result, compiler=compiler,
                            compiler_sha256=digest, timeout_seconds=3)
        self.assertLess(time.monotonic() - started, 3)

    def test_revalidates_request_and_result_before_launch(self):
        compiler, digest = self.compiler()
        wrong_request = dict(self.request)
        wrong_request["request_digest"] = "0" * 64
        with self.assertRaisesRegex(PreviewError, "contract validation"):
            compile_preview(wrong_request, self.result, compiler=compiler, compiler_sha256=digest)
        wrong_result = dict(self.result)
        wrong_result["request_digest"] = "0" * 64
        with self.assertRaisesRegex(PreviewError, "contract validation"):
            compile_preview(self.request, wrong_result, compiler=compiler, compiler_sha256=digest)


@unittest.skipUnless(os.environ.get("HYPERREVIEW_TEST_COMPILER"),
                     "set HYPERREVIEW_TEST_COMPILER to exercise the trusted compiler")
class RealCompilerIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiler = Path(os.environ["HYPERREVIEW_TEST_COMPILER"])
        if not cls.compiler.is_absolute():
            raise AssertionError("HYPERREVIEW_TEST_COMPILER must be absolute")
        cls.compiler_sha256 = hashlib.sha256(cls.compiler.read_bytes()).hexdigest()

    def setUp(self):
        self.request = make_request()
        before_refs = [source["id"] for source in self.request["sources"] if source["side"] == "before"]
        after_refs = [source["id"] for source in self.request["sources"] if source["side"] == "after"]
        self.result = make_result(self.request)
        self.result["before_hc"] = "Application#App\n"
        self.result["after_hc"] = "Application#App\n  Assessment#Assessment\n"
        self.result["identity_map"] = [
            {"architecture_id": "#App", "before_refs": before_refs,
             "after_refs": after_refs, "reason": "The application remains."},
            {"architecture_id": "#Assessment", "before_refs": [],
             "after_refs": after_refs, "reason": "The assessment is added."},
        ]
        self.result["claims"][0]["architecture_ids"] = ["#App", "#Assessment"]

    def test_real_compiler_accepts_controlled_added_node(self):
        preview = compile_preview(self.request, self.result, compiler=self.compiler,
                                  compiler_sha256=self.compiler_sha256)
        self.assertEqual(preview["receipt"]["before_ids"], ["App"])
        self.assertEqual(preview["receipt"]["after_ids"], ["App", "Assessment"])

    def test_real_compiler_ids_must_match_model_identity_map(self):
        wrong = json.loads(intake.encoded(self.result))
        wrong["identity_map"][1]["architecture_id"] = "#Invented"
        wrong["claims"][0]["architecture_ids"] = ["#App", "#Invented"]
        with self.assertRaisesRegex(PreviewError, "IR IDs do not match"):
            compile_preview(self.request, wrong, compiler=self.compiler,
                            compiler_sha256=self.compiler_sha256)

    def test_real_compiler_arrow_syntax_has_expected_sanitized_parse_identity(self):
        result = json.loads(intake.encoded(self.result))
        result["after_hc"] = "Application#App -> Assessment#Assessment\n"
        with self.assertRaises(CompilerCommandError) as caught:
            compile_preview(self.request, result, compiler=self.compiler,
                            compiler_sha256=self.compiler_sha256)
        self.assertEqual(caught.exception.operation, "parse")
        self.assertEqual(caught.exception.return_code, 1)
        self.assertEqual(caught.exception.diagnostic_codes, ("HC1001",))


if __name__ == "__main__":
    unittest.main()
