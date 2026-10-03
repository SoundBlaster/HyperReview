import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from hyperreview import intake
from hyperreview.model_contract import ABSTRACTION_PROFILE, PROMPT_VERSION
from hyperreview.tracking import (TrackingError, pending_events, reconcile, validate_event)


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


if __name__ == "__main__":
    unittest.main()
