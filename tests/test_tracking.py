import copy
import hashlib
import json
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

from hyperreview import intake
from hyperreview.model_contract import ABSTRACTION_PROFILE, PROMPT_VERSION
from hyperreview.tracking import (TrackingError, _run_delivery, build_event, pending_events, reconcile, validate_event)
from hyperreview.model_contract import prepare_request
from test_model_contract import pack, source, valid_result


def event():
    return {
        "schema": "hyperreview.tracking-event.v1", "correlation_id": "a" * 8 + "-" + "b" * 4
        + "-" + "c" * 4 + "-" + "d" * 4 + "-" + "e" * 12, "attempt": 1,
        "metadata": {
            "repository": "0al-spec/SpecGraph", "pr": "761", "merge_base_sha": "a" * 40,
            "head_sha": "b" * 40, "evidence_digest": "c" * 64, "request_digest": "d" * 64,
            "result_digest": "e" * 64, "abstraction_profile": ABSTRACTION_PROFILE,
            "prompt_version": PROMPT_VERSION, "provider": "lmstudio",
            "model_identity_sha256": "f" * 64, "compiler_sha256": "a" * 64,
            "compiler_resolver_name": "hypercode-swift", "compiler_resolver_version": "0.6.0-dev",
            "delivery_mode": "preview",
        },
        "metrics": {"included_source_records": 1, "omissions": 24, "input_tokens": 2151},
        "stages": [{"name": name, "status": "completed", "elapsed_ms": None}
                   for name in ("collection", "inference", "projection_validation", "rendering")],
    }


def receipt(value):
    return {"schema": "hyperreview.tracking-receipt.v1", "correlation_id": value["correlation_id"],
            "attempt": 1, "tracking_status": "confirmed", "experiment_id": "1", "run_id": "r" * 32,
            "trace_id": "tr-" + "a" * 32, "event_digest": intake.digest(value)}


class TrackingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.arguments = {"spool_root": self.root / "spool", "runtime_python": Path("/trusted/python"),
                          "database": self.root / "db.sqlite", "artifacts_root": self.root / "artifacts"}

    def test_only_fixed_metadata_and_integer_metrics_are_allowed(self):
        self.assertEqual(validate_event(event()), event())
        for area, name, value in (("metadata", "source", "print(secret)"),
                                  ("metrics", "token", "credential"),
                                  ("metrics", "input_tokens", True),
                                  ("metadata", "compiler_resolver_version", "<script>")):
            candidate = event()
            candidate[area][name] = value
            with self.subTest(area=area, name=name), self.assertRaises(TrackingError):
                validate_event(candidate)

    def test_codex_provider_is_an_explicit_tracking_identity(self):
        candidate = event()
        candidate["metadata"]["provider"] = "codex"
        self.assertEqual(validate_event(candidate), candidate)
        candidate["metadata"]["provider"] = "automatic_fallback"
        with self.assertRaises(TrackingError):
            validate_event(candidate)

    def test_event_is_persisted_before_delivery_and_receipt_survives_replay(self):
        value = event()
        calls = []
        def deliver(candidate, *_args):
            path = self.arguments["spool_root"] / (value["correlation_id"] + ".json")
            self.assertEqual(json.loads(path.read_bytes()), value)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            calls.append(candidate)
            return receipt(candidate)
        confirmed = reconcile(value, **self.arguments, delivery=deliver)
        self.assertEqual(confirmed, receipt(value))
        self.assertEqual(len(calls), 1)
        self.assertEqual(list(pending_events(self.arguments["spool_root"])), [])
        self.assertEqual(reconcile(value, **self.arguments, delivery=deliver), confirmed)
        self.assertEqual(len(calls), 1)

    def test_failed_delivery_keeps_same_pending_event(self):
        value = event()
        def fail(*_args):
            raise TrackingError("fixture unavailable")
        with self.assertRaises(TrackingError):
            reconcile(value, **self.arguments, delivery=fail)
        self.assertEqual(list(pending_events(self.arguments["spool_root"])), [value])
        confirmed = reconcile(value, **self.arguments, delivery=lambda candidate, *_: receipt(candidate))
        self.assertEqual(confirmed["correlation_id"], value["correlation_id"])

    def test_conflicting_event_or_receipt_is_not_overwritten(self):
        value = event()
        confirmed = reconcile(value, **self.arguments, delivery=lambda candidate, *_: receipt(candidate))
        changed = copy.deepcopy(value)
        changed["metrics"]["omissions"] += 1
        with self.assertRaises(TrackingError):
            reconcile(changed, **self.arguments, delivery=lambda *_: confirmed)

    def test_invalid_delivery_receipt_stays_pending(self):
        value = event()
        bad = receipt(value)
        bad["event_digest"] = "0" * 64
        with self.assertRaises(TrackingError):
            reconcile(value, **self.arguments, delivery=lambda *_: bad)
        self.assertEqual(list(pending_events(self.arguments["spool_root"])), [value])

    def test_reconcile_cleans_event_left_after_durable_receipt_before_yielding_next(self):
        first = event()
        later = event()
        later["correlation_id"] = str(uuid4())
        spool = self.arguments["spool_root"]
        spool.mkdir(mode=0o700)
        first_event = spool / (first["correlation_id"] + ".json")
        first_receipt = spool / (first["correlation_id"] + ".receipt.json")
        later_event = spool / (later["correlation_id"] + ".json")
        first_event.write_bytes(intake.encoded(first))
        first_receipt.write_bytes(intake.encoded(receipt(first)))
        later_event.write_bytes(intake.encoded(later))
        calls = []

        confirmed = reconcile(
            first,
            **self.arguments,
            delivery=lambda *args: calls.append(args),
        )

        self.assertEqual(confirmed, receipt(first))
        self.assertEqual(calls, [])
        self.assertFalse(first_event.exists())
        self.assertTrue(first_receipt.exists())
        self.assertEqual(list(pending_events(spool)), [later])

    def test_invalid_existing_receipt_keeps_event_pending(self):
        value = event()
        spool = self.arguments["spool_root"]
        spool.mkdir(mode=0o700)
        event_path = spool / (value["correlation_id"] + ".json")
        receipt_path = spool / (value["correlation_id"] + ".receipt.json")
        invalid = receipt(value)
        invalid["event_digest"] = "0" * 64
        event_path.write_bytes(intake.encoded(value))
        receipt_path.write_bytes(intake.encoded(invalid))
        calls = []

        with self.assertRaises(TrackingError):
            reconcile(
                value,
                **self.arguments,
                delivery=lambda *args: calls.append(args),
            )

        self.assertEqual(calls, [])
        self.assertTrue(event_path.exists())
        self.assertTrue(receipt_path.exists())
        self.assertEqual(list(pending_events(spool)), [value])

    def test_pending_budget_and_symlink_paths(self):
        with patch("hyperreview.tracking.MAX_PENDING_EVENTS", 0):
            with self.assertRaisesRegex(TrackingError, "spool is full"):
                reconcile(event(), **self.arguments, delivery=lambda *_: receipt(event()))
        target = self.root / "real"
        target.mkdir()
        link = self.root / "linked"
        link.symlink_to(target, target_is_directory=True)
        arguments = {**self.arguments, "spool_root": link}
        with self.assertRaisesRegex(TrackingError, "symlinks"):
            reconcile(event(), **arguments)

    def test_bundle_export_contains_no_source_model_prose_paths_or_model_name(self):
        evidence = pack([source("after", "private_source_sentinel\n")])
        request = prepare_request(evidence)
        result = valid_result(request)
        result["summary"] = "private_model_summary_sentinel"
        result["before_hc"] = "\n"
        result["after_hc"] = "Application#App\n"
        bound = {"request_digest": request["request_digest"], "result_digest": intake.digest(result)}
        compiler = {**bound, "stage": "projections_validated", "compiler_sha256": "a" * 64,
                    "before_resolver": {"name": "hypercode-swift", "version": "0.6.0-dev"},
                    "after_resolver": {"name": "hypercode-swift", "version": "0.6.0-dev"},
                    "before_ids": [], "after_ids": ["App"], "change_count": 1, "elapsed_ms": 2}
        values = {
            "evidence.json": evidence, "request.json": request, "result.json": result,
            "metadata.json": {**bound, "schema": "hyperreview.preview.v1", "stage": "projections_validated",
                              "tracking_correlation_id": str(uuid4()), "delivery_mode": "preview", "attempt": 1},
            "generation-receipt.json": {**bound, "stage": "model_generated", "provider": "lmstudio",
                                        "model": "private_model_name_sentinel", "elapsed_ms": 1,
                                        "input_tokens": None, "output_tokens": None},
        }
        for name, field in (("before.ir.json", "before_ir_sha256"),
                            ("after.ir.json", "after_ir_sha256"), ("diff.json", "diff_sha256")):
            raw = intake.encoded({"fixture": name})
            (self.root / name).write_bytes(raw)
            compiler[field] = hashlib.sha256(raw).hexdigest()
        values["compiler-receipt.json"] = compiler
        for name, value in values.items():
            (self.root / name).write_bytes(intake.encoded(value))
        (self.root / "before.hc").write_text(result["before_hc"])
        (self.root / "after.hc").write_text(result["after_hc"])
        (self.root / "preview.md").write_text("private_preview_sentinel")
        exported = build_event(self.root)
        serialized = intake.encoded(exported).decode()
        for sentinel in ("private_source_sentinel", "private_model_summary_sentinel",
                         "private_model_name_sentinel", "private_preview_sentinel", "src/app.py"):
            self.assertNotIn(sentinel, serialized)
        self.assertNotIn("input_tokens", exported["metrics"])
        generation = values["generation-receipt.json"]
        generation.update(provider="codex", reasoning_effort="low")
        (self.root / "generation-receipt.json").write_bytes(intake.encoded(generation))
        codex_event = build_event(self.root)
        self.assertEqual(codex_event["metadata"]["provider"], "codex")
        self.assertEqual(codex_event["metadata"]["model_identity_sha256"],
                         intake.digest({"model": generation["model"], "reasoning_effort": "low"}))
        self.assertNotIn("private_model_name_sentinel", intake.encoded(codex_event).decode())
        generation.pop("reasoning_effort")
        (self.root / "generation-receipt.json").write_bytes(intake.encoded(generation))
        with self.assertRaisesRegex(TrackingError, "reasoning effort"):
            build_event(self.root)
        (self.root / "after.ir.json").write_bytes(b"modified")
        with self.assertRaisesRegex(TrackingError, "fingerprint mismatch"):
            build_event(self.root)

    def test_spool_cannot_be_silently_redirected_to_another_store(self):
        value = event()
        reconcile(value, **self.arguments, delivery=lambda candidate, *_: receipt(candidate))
        arguments = {**self.arguments, "database": self.root / "other.sqlite"}
        with self.assertRaisesRegex(TrackingError, "another destination"):
            reconcile(value, **arguments, delivery=lambda *_: receipt(value))

    def runtime(self, body):
        script = self.root / "fixture-runtime"
        script.write_text(f"#!{sys.executable}\n" + body)
        script.chmod(0o700)
        return script

    def test_delivery_child_gets_only_sanitized_input_and_minimal_environment(self):
        script = self.runtime(
            "import os,sys,json,hashlib\n"
            "assert os.getenv('HYPERREVIEW_PRIVATE_SENTINEL') is None\n"
            "event=json.load(sys.stdin)\n"
            "assert 'sources' not in event and 'result' not in event\n"
            "raw=json.dumps(event,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()\n"
            "receipt={'schema':'hyperreview.tracking-receipt.v1','correlation_id':event['correlation_id'],"
            "'attempt':1,'tracking_status':'confirmed','experiment_id':'1','run_id':'fixture-run',"
            "'trace_id':'fixture-trace','event_digest':hashlib.sha256(raw).hexdigest()}\n"
            "print(json.dumps(receipt))\n")
        with patch.dict("os.environ", {"HYPERREVIEW_PRIVATE_SENTINEL": "do-not-inherit"}):
            confirmed = _run_delivery(event(), script, self.arguments["database"],
                                      self.arguments["artifacts_root"], 5)
        self.assertEqual(confirmed["event_digest"], intake.digest(event()))

    def test_delivery_child_output_and_total_time_are_bounded(self):
        for body, timeout in (("import sys\nsys.stdout.write('X'*65537)\nsys.stdout.flush()\n", 5),
                              ("import time\ntime.sleep(3)\n", 1)):
            with self.subTest(body=body):
                script = self.runtime(body)
                with self.assertRaises(TrackingError):
                    _run_delivery(event(), script, self.arguments["database"],
                                  self.arguments["artifacts_root"], timeout)


if __name__ == "__main__":
    unittest.main()
