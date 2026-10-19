import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

from hyperreview import intake, model_contract, worker_generation
from hyperreview.codex_provider import CodexConfig
from hyperreview.codex_isolation import IsolationError
from hyperreview.composition_plan import to_result
from hyperreview.worker_generation import PreviewJobError, fingerprint, run, validate_options
from test_local_provider import make_plan, make_result


def evidence_and_request():
    content = "def assess():\n    return True\n"
    source = {
        "side": "after", "revision": "b" * 40, "path": "src/assessment.py",
        "content": content, "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
        "content_bytes": len(content.encode()), "line_start": 1, "line_end": 2,
        "trust": "untrusted_source_data", "url": "https://example.invalid/source",
    }
    evidence = {
        "schema": intake.SCHEMA, "stage": "evidence_collected",
        "repository": "0al-spec/SpecGraph", "pr": 17, "author": intake.AUTHOR,
        "authenticated_account": intake.AUTHOR, "base_repo": "0al-spec/SpecGraph",
        "head_repo": "0al-spec/SpecGraph", "state": "open", "draft": False,
        "base_sha": "c" * 40, "merge_base_sha": "a" * 40, "head_sha": "b" * 40,
        "selector_context": {"before_hcs_present": False, "after_hcs_present": False},
        "files": [{"before_path": None, "after_path": "src/assessment.py",
                    "sources": [source], "omissions": []}],
    }
    evidence["evidence_digest"] = intake.digest(evidence)
    return evidence, model_contract.prepare_request(evidence)


class WorkerGenerationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.compiler = root / "hypercode"
        self.compiler.write_bytes(b"pinned compiler fixture")
        self.compiler.chmod(0o700)
        self.codex = root / "codex"
        self.codex.write_bytes(b"configured native binary fixture")
        self.codex.chmod(0o700)
        self.options = {
            "allow_cloud_source": True, "codex_executable": str(self.codex),
            "codex_sha256": hashlib.sha256(self.codex.read_bytes()).hexdigest(),
            "compiler": str(self.compiler),
            "compiler_sha256": hashlib.sha256(self.compiler.read_bytes()).hexdigest(),
            "model": "gpt-6-luna", "reasoning_effort": "low", "timeout_seconds": 30,
        }
        self.evidence, self.request = evidence_and_request()

    def tearDown(self):
        self.temporary.cleanup()

    def _generated(self, *, receipt_overrides=None):
        plan = make_plan(self.request)
        result = to_result(plan, self.request)
        receipt = {
            "provider": "codex", "executable_sha256": self.options["codex_sha256"],
            "request_digest": self.request["request_digest"],
            "result_digest": intake.digest(result), "attempt_count": 1,
            "process_isolation": {"mode": "macos-seatbelt-v1"},
        }
        receipt.update(receipt_overrides or {})
        return {"plan": plan, "result": result, "receipt": receipt}

    def _compiled(self):
        return {"artifacts": {
            "before.hc": b"before", "after.hc": b"after",
            "before.ir.json": b"{}", "after.ir.json": b"{}", "diff.json": b'{"version":"hypercode.diff/v1","changes":[]}',
            "result.json": intake.encoded(make_result(self.request)),
            "request.json": intake.encoded(self.request), "compiler-receipt.json": b"{}",
        }, "receipt": {"compiler_sha256": self.options["compiler_sha256"]}}

    def _run_mocks(self, generated=None, *, compile_side_effect=None):
        generated = generated or self._generated()
        config = CodexConfig(executable=str(self.codex), timeout_seconds=1,
                             allow_cloud_source=True, isolate_process=True,
                             expected_executable_sha256=self.options["codex_sha256"])
        provider = patch("hyperreview.codex_provider.generate", return_value=generated)
        compiler = patch("hyperreview.compiled_preview.compile_preview",
                         side_effect=compile_side_effect, return_value=self._compiled())
        patches = [
            patch("hyperreview.worker_generation._validate_native_codex", return_value=config),
            provider,
            compiler,
            patch("hyperreview.render.render_preview", return_value=b"verbose"),
            patch("hyperreview.render.render_compact_preview", return_value=b"compact"),
        ]
        return patches, provider, compiler

    def test_options_are_closed_and_portable(self):
        self.assertIs(validate_options(self.options), self.options)
        for mutate in (
            lambda values: values.update(extra_provider="ollama"),
            lambda values: values.update(allow_cloud_source=False),
            lambda values: values.update(timeout_seconds=True),
            lambda values: values.update(model="m\nunsafe"),
        ):
            options = dict(self.options)
            mutate(options)
            with self.subTest(options=options), self.assertRaises(PreviewJobError) as caught:
                validate_options(options)
            self.assertEqual(caught.exception.code, "invalid_preview_config")

    def test_fingerprint_is_stable_and_binds_configuration(self):
        self.assertEqual(fingerprint(self.options), fingerprint(dict(self.options)))
        changed = dict(self.options, model="gpt-6-other")
        self.assertNotEqual(fingerprint(self.options), fingerprint(changed))

    def test_fingerprint_works_from_package_without_checkout_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            package_root = Path(temporary) / "site-packages"
            package = package_root / "hyperreview"
            package.mkdir(parents=True)
            for relative in worker_generation._FINGERPRINT_FILES:
                source = Path(worker_generation.__file__).resolve().parent.parent / relative
                destination = package_root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
            with patch("hyperreview.worker_generation.__file__",
                       str(package / "worker_generation.py")):
                self.assertEqual(len(fingerprint(self.options)), 64)
            self.assertFalse((package_root / "pyproject.toml").exists())

    def test_native_codex_configuration_pins_executable_hash(self):
        with patch("hyperreview.worker_generation.sys.platform", "darwin"), \
                patch("hyperreview.codex_provider._resolve_executable",
                      return_value=(self.codex, self.options["codex_sha256"])):
            config = worker_generation._validate_native_codex(
                self.options, time.monotonic() + 30)
        self.assertEqual(config.expected_executable_sha256, self.options["codex_sha256"])

    def test_native_codex_isolation_errors_are_sanitized(self):
        with patch("hyperreview.worker_generation.sys.platform", "darwin"), \
                patch("hyperreview.codex_provider._resolve_executable",
                      side_effect=IsolationError("not a native Mach-O")):
            with self.assertRaises(PreviewJobError) as caught:
                worker_generation._validate_native_codex(self.options, time.monotonic() + 30)
        self.assertEqual(caught.exception.code, "codex_preflight_failed")

    def test_compiler_pin_is_checked_before_model_preflight(self):
        self.compiler.write_bytes(b"tampered")
        with patch("hyperreview.worker_generation._validate_native_codex") as preflight, \
                patch("hyperreview.codex_provider.generate") as provider:
            with self.assertRaises(PreviewJobError) as caught:
                run(self.evidence, self.request, self.options)
        self.assertEqual(caught.exception.code, "invalid_preview_config")
        preflight.assert_not_called()
        provider.assert_not_called()

    def test_model_call_forces_isolation_and_emits_canonical_preview(self):
        patches, _, _ = self._run_mocks()
        with patch("hyperreview.worker_generation.sys.platform", "darwin"):
            mocks = [item.start() for item in patches]
            try:
                outcome = run(self.evidence, self.request, self.options)
            finally:
                for item in reversed(patches):
                    item.stop()
        config = mocks[1].call_args.args[1]
        self.assertTrue(config.allow_cloud_source)
        self.assertTrue(config.isolate_process)
        self.assertEqual(config.expected_executable_sha256, self.options["codex_sha256"])
        self.assertGreaterEqual(config.timeout_seconds, 1)
        self.assertLessEqual(config.timeout_seconds, 29)
        self.assertLessEqual(mocks[2].call_args.kwargs["timeout_seconds"], 120)
        artifacts = outcome["artifacts"]
        self.assertEqual(len(artifacts), 14)
        metadata = json.loads(artifacts["metadata.json"])
        self.assertEqual(metadata["schema"], "hyperreview.preview.v1")
        self.assertEqual(metadata["stage"], "projections_validated")
        self.assertEqual(metadata["delivery_mode"], "preview")
        self.assertEqual(metadata["tracking_status"], "not_started")
        self.assertEqual(metadata["attempt"], 1)
        generation = json.loads(artifacts["generation-receipt.json"])
        self.assertEqual(generation["stage"], "model_generated")
        self.assertEqual(generation["hypercode_validation"], "not_started")
        self.assertEqual(generation["tracking_status"], "not_started")
        self.assertEqual(outcome["provider_attempts"], 1)

    def test_post_generation_executable_pin_or_isolation_failure_is_rejected(self):
        for changes in (
            {"executable_sha256": "0" * 64},
            {"process_isolation": {"mode": "none"}},
            {"attempt_count": 3},
        ):
            patches, _, _ = self._run_mocks(
                self._generated(receipt_overrides=changes))
            with patch("hyperreview.worker_generation.sys.platform", "darwin"):
                mocks = [item.start() for item in patches]
                try:
                    with self.assertRaises(PreviewJobError) as caught:
                        run(self.evidence, self.request, self.options)
                finally:
                    for item in reversed(patches):
                        item.stop()
            self.assertEqual(caught.exception.code, "generation_failed")
            mocks[2].assert_not_called()

    def test_compilation_failure_has_stable_sanitized_code(self):
        patches, _, _ = self._run_mocks(
            compile_side_effect=RuntimeError("private prompt must not escape"))
        with patch("hyperreview.worker_generation.sys.platform", "darwin"):
            [item.start() for item in patches]
            try:
                with self.assertRaises(PreviewJobError) as caught:
                    run(self.evidence, self.request, self.options)
            finally:
                for item in reversed(patches):
                    item.stop()
        self.assertEqual(caught.exception.code, "compilation_failed")
        self.assertEqual(str(caught.exception), "compilation_failed")

    def test_shared_deadline_expiry_after_generation_is_terminal(self):
        patches, _, _ = self._run_mocks()
        with patch("hyperreview.worker_generation.sys.platform", "darwin"), \
                patch("hyperreview.worker_generation.time.monotonic",
                      side_effect=[0, 0, 0, 2, 31]):
            mocks = [item.start() for item in patches]
            try:
                with self.assertRaises(PreviewJobError) as caught:
                    run(self.evidence, self.request, self.options)
            finally:
                for item in reversed(patches):
                    item.stop()
        self.assertEqual(caught.exception.code, "generation_failed")
        mocks[1].assert_called_once()
        mocks[2].assert_not_called()

    def test_render_failure_is_sanitized(self):
        patches, _, _ = self._run_mocks()
        patches[-2] = patch("hyperreview.render.render_preview",
                            side_effect=RuntimeError("source text must not escape"))
        with patch("hyperreview.worker_generation.sys.platform", "darwin"):
            [item.start() for item in patches]
            try:
                with self.assertRaises(PreviewJobError) as caught:
                    run(self.evidence, self.request, self.options)
            finally:
                for item in reversed(patches):
                    item.stop()
        self.assertEqual(caught.exception.code, "preview_render_failed")

    def test_unsupported_platform_fails_closed(self):
        with patch("hyperreview.worker_generation.sys.platform", "linux"), \
                patch("hyperreview.codex_provider.generate") as provider:
            with self.assertRaises(PreviewJobError) as caught:
                run(self.evidence, self.request, self.options)
        self.assertEqual(caught.exception.code, "codex_preflight_failed")
        provider.assert_not_called()


if __name__ == "__main__":
    unittest.main()
