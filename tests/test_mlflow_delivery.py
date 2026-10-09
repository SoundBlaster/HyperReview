import hashlib
import importlib
import io
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from hyperreview import mlflow_delivery as delivery


def fixture_event():
    metadata = {
        "repository": "0al-spec/Hypercode",
        "pr": "42",
        "merge_base_sha": "a" * 40,
        "head_sha": "b" * 40,
        "evidence_digest": "c" * 64,
        "request_digest": "d" * 64,
        "result_digest": "e" * 64,
        "abstraction_profile": "hyperreview.safe-diff.v1",
        "prompt_version": "hyperreview.prompt.v1",
        "provider": "ollama",
        "model_identity_sha256": "f" * 64,
        "compiler_sha256": "1" * 64,
        "compiler_resolver_name": "hypercode-swift",
        "compiler_resolver_version": "1.2.3",
        "delivery_mode": "preview",
    }
    return {
        "schema": delivery.EVENT_SCHEMA,
        "correlation_id": "07686ef4-3b67-456c-ae7c-83d06cc19152",
        "attempt": 1,
        "metadata": metadata,
        "metrics": {"change_count": 2, "inference_elapsed_ms": 125},
        "stages": [
            {"name": "collection", "status": "completed", "elapsed_ms": None},
            {"name": "inference", "status": "completed", "elapsed_ms": 125},
            {"name": "projection_validation", "status": "completed", "elapsed_ms": 7},
            {"name": "rendering", "status": "completed", "elapsed_ms": None},
        ],
    }


class Page(list):
    token = None


class Attr:
    def __init__(self, **values):
        self.__dict__.update(values)


class FakeSpan:
    next_id = 1

    def __init__(self, trace_id, name, span_id=None, attributes=None, inputs=None):
        self.trace_id = trace_id
        self.span_id = span_id or f"span-{FakeSpan.next_id}"
        FakeSpan.next_id += 1
        self.name = name
        self.attributes = attributes or {}
        self.inputs = inputs
        self.is_recording = lambda: True


class FakeClient:
    def __init__(self, uri, *, artifact_location=None):
        self.tracking_uri = uri
        self.experiment = None
        self.runs = {}
        self.traces = {}
        self.metrics = {}
        self.metric_writes = 0
        self.trace_starts = 0
        self.fail_run_reply_once = False
        self.incomplete_next_trace = False
        self.fail_trace_reply_once = False
        self.run_page_once = False
        self.trace_page_once = False
        self.existing_artifact_location = artifact_location

    def get_experiment_by_name(self, _name):
        return self.experiment

    def create_experiment(self, _name, artifact_location=None):
        self.experiment = Attr(experiment_id="experiment-1",
                               artifact_location=artifact_location)
        return self.experiment.experiment_id

    def get_experiment(self, _experiment_id):
        return self.experiment

    def install_experiment(self, uri):
        self.experiment = Attr(experiment_id="experiment-1", artifact_location=uri)

    def create_run(self, experiment_id, tags, run_name):
        run_id = f"run-{len(self.runs) + 1}"
        run = Attr(info=Attr(run_id=run_id, experiment_id=experiment_id,
                             status="RUNNING", run_name=run_name),
                   data=Attr(tags=dict(tags), metrics={}))
        self.runs[run_id] = run
        if self.fail_run_reply_once:
            self.fail_run_reply_once = False
            raise OSError("secret/raw SDK diagnostic that must not be exposed")
        return run

    def search_runs(self, _experiment_ids, filter_string, **_kwargs):
        if self.run_page_once:
            self.run_page_once = False
            page = Page()
            page.token = "run-next-page"
            return page
        identifier = filter_string.split("'")[1]
        attempt = filter_string.split("'")[3]
        rows = [
            run for run in self.runs.values()
            if run.data.tags.get("hyperreview_correlation_id") == identifier
            and run.data.tags.get("hyperreview_attempt") == attempt
        ]
        return Page(rows)

    def get_run(self, run_id):
        return self.runs[run_id]

    def set_tag(self, run_id, key, value, **_kwargs):
        self.runs[run_id].data.tags[key] = value

    def get_metric_history(self, run_id, name):
        return list(self.metrics.get((run_id, name), []))

    def log_metric(self, run_id, name, value, **_kwargs):
        self.metric_writes += 1
        self.metrics.setdefault((run_id, name), []).append(Attr(value=float(value)))

    def start_trace(self, name, tags, experiment_id, run_id, **kwargs):
        self.trace_starts += 1
        trace_id = f"trace-{self.trace_starts}"
        root = FakeSpan(
            trace_id,
            name,
            span_id="root",
            attributes=kwargs.get("attributes"),
            inputs=kwargs.get("inputs"),
        )
        info = Attr(
            trace_id=trace_id,
            status="IN_PROGRESS",
            tags=dict(tags),
            experiment_id=experiment_id,
            trace_metadata={"mlflow.sourceRun": run_id},
        )
        self.traces[trace_id] = Attr(info=info, data=Attr(spans=[root]), outputs=None)
        return root

    def start_span(self, name, trace_id, **_kwargs):
        span = FakeSpan(
            trace_id,
            name,
            attributes=_kwargs.get("attributes"),
            inputs=_kwargs.get("inputs"),
        )
        self.traces[trace_id].data.spans.append(span)
        return span

    def end_span(self, trace_id, span_id, outputs=None, status="OK"):
        self.traces[trace_id].outputs = outputs
        self.traces[trace_id].last_span_status = status

    def end_trace(self, trace_id, outputs=None, status="OK", **_kwargs):
        trace = self.traces[trace_id]
        trace.info.status = "IN_PROGRESS" if self.incomplete_next_trace else status
        self.incomplete_next_trace = False
        trace.outputs = outputs
        if self.fail_trace_reply_once:
            self.fail_trace_reply_once = False
            raise OSError("private SDK response text")

    def search_traces(self, filter_string, **_kwargs):
        if self.trace_page_once:
            self.trace_page_once = False
            page = Page()
            page.token = "trace-next-page"
            return page
        identifier = filter_string.split("'")[1]
        attempt = filter_string.split("'")[3]
        rows = [
            trace for trace in self.traces.values()
            if trace.info.tags.get("hyperreview_correlation_id") == identifier
            and trace.info.tags.get("hyperreview_attempt") == attempt
        ]
        return Page(rows)

    def get_trace(self, trace_id, **_kwargs):
        return self.traces[trace_id]

    def set_terminated(self, run_id, status):
        self.runs[run_id].info.status = status


class MlflowDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.database = self.root / "tracking.db"
        self.artifacts = self.root / "artifacts"
        self.artifacts.mkdir()
        self.event = fixture_event()
        self.module = types.SimpleNamespace(validate_event=self.validate)
        self.module_patch = patch.dict(sys.modules, {"hyperreview.tracking": self.module})
        self.module_patch.start()
        self.addCleanup(self.module_patch.stop)
        FakeSpan.next_id = 1
        self.client = None

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def validate(event):
        if type(event) is not dict or event.get("schema") != delivery.EVENT_SCHEMA:
            raise ValueError("invalid event")
        return event

    def factory(self, uri):
        self.assertEqual(uri, f"sqlite:///{self.database}")
        if self.client is None:
            self.client = FakeClient(uri)
        return self.client

    def send(self):
        return delivery.deliver(
            self.event,
            self.database,
            self.artifacts,
            client_factory=self.factory,
        )

    def test_manual_delivery_is_metadata_only_and_confirmed(self):
        receipt = self.send()
        self.assertEqual(receipt["tracking_status"], "confirmed")
        self.assertEqual(receipt["run_id"], "run-1")
        self.assertEqual(receipt["trace_id"], "trace-1")
        self.assertEqual(receipt["event_digest"], self.digest(self.event))
        run = self.client.runs["run-1"]
        trace = self.client.traces["trace-1"]
        self.assertEqual(run.data.tags["hyperreview_correlation_id"], self.event["correlation_id"])
        self.assertEqual(run.data.tags["hyperreview_attempt"], "1")
        self.assertEqual(trace.info.tags["hyperreview_event_digest"], receipt["event_digest"])
        self.assertEqual(len(trace.data.spans), 5)
        self.assertEqual(
            [span.name for span in trace.data.spans],
            [
                "hyperreview.preview.receipt_export",
                "collection",
                "inference",
                "projection_validation",
                "rendering",
            ],
        )
        self.assertEqual(trace.data.spans[2].name, "inference")
        self.assertEqual(trace.info.status, "OK")
        self.assertIsNone(trace.data.spans[0].inputs)
        self.assertIsNone(trace.outputs)
        self.assertEqual(
            trace.data.spans[0].attributes["hyperreview.recording_mode"],
            "retrospective_receipt",
        )
        self.assertNotIn("model_response", json.dumps(trace.data.spans[0].attributes))
        self.assertEqual(self.client.metric_writes, 2)

    def test_replay_adopts_run_and_trace_without_duplicate_metric_or_trace(self):
        first = self.send()
        second = self.send()
        self.assertEqual(first, second)
        self.assertEqual(len(self.client.runs), 1)
        self.assertEqual(len(self.client.traces), 1)
        self.assertEqual(self.client.metric_writes, 2)
        self.assertEqual(self.client.trace_starts, 1)

    def test_lost_create_run_reply_is_reconciled_by_correlation_tag(self):
        self.client = FakeClient(f"sqlite:///{self.database}")
        self.client.fail_run_reply_once = True
        receipt = self.send()
        self.assertEqual(receipt["run_id"], "run-1")
        self.assertEqual(len(self.client.runs), 1)

    def test_run_and_trace_searches_follow_page_tokens(self):
        self.client = FakeClient(f"sqlite:///{self.database}")
        self.client.run_page_once = True
        self.client.trace_page_once = True
        receipt = self.send()
        self.assertEqual(receipt["tracking_status"], "confirmed")
        self.assertEqual(self.client.trace_starts, 1)

    def test_lost_trace_completion_reply_is_adopted_without_duplicate(self):
        self.client = FakeClient(f"sqlite:///{self.database}")
        self.client.fail_trace_reply_once = True
        with self.assertRaises(delivery.DeliveryError) as raised:
            self.send()
        self.assertEqual(raised.exception.code, "trace_write_failed")
        self.assertEqual(len(self.client.traces), 1)
        receipt = self.send()
        self.assertEqual(receipt["trace_id"], "trace-1")
        self.assertEqual(self.client.trace_starts, 1)

    def test_multiple_run_matches_are_a_conflict(self):
        self.send()
        original = self.client.runs["run-1"]
        duplicate = Attr(
            info=Attr(run_id="run-duplicate", experiment_id="experiment-1",
                      status="RUNNING", run_name="duplicate"),
            data=Attr(tags=dict(original.data.tags), metrics={}),
        )
        self.client.runs[duplicate.info.run_id] = duplicate
        with self.assertRaises(delivery.DeliveryError) as raised:
            self.send()
        self.assertEqual(raised.exception.code, "run_conflict")
        self.assertEqual(len(self.client.traces), 1)

    def test_incomplete_existing_trace_is_pending_and_never_recreated(self):
        digest = self.digest(self.event)
        self.client = FakeClient(f"sqlite:///{self.database}")
        self.client.install_experiment(self.artifacts.as_uri())
        trace_id = "old-trace"
        self.client.traces[trace_id] = Attr(
            info=Attr(
                trace_id=trace_id,
                status="IN_PROGRESS",
                tags=delivery._trace_tags(
                    self.event["correlation_id"], self.event["attempt"], digest
                ),
                experiment_id="experiment-1",
            ),
            data=Attr(spans=[]),
        )
        with self.assertRaises(delivery.DeliveryError) as raised:
            self.send()
        self.assertEqual(raised.exception.code, "incomplete_trace")
        self.assertEqual(self.client.trace_starts, 0)
        self.assertEqual(len(self.client.traces), 1)

    def test_metric_history_conflict_is_not_appended(self):
        self.client = FakeClient(f"sqlite:///{self.database}")
        self.send()
        self.client.metrics[("run-1", "change_count")] = [Attr(value=99.0)]
        with self.assertRaises(delivery.DeliveryError) as raised:
            self.send()
        self.assertEqual(raised.exception.code, "metric_conflict")

    def test_malformed_event_rejected_before_sdk_factory(self):
        self.event["metadata"]["unexpected"] = "not allowed"
        called = []
        with self.assertRaises(delivery.DeliveryError) as raised:
            delivery.deliver(
                self.event,
                self.database,
                self.artifacts,
                client_factory=lambda uri: called.append(uri),
            )
        self.assertEqual(raised.exception.code, "invalid_event")
        self.assertEqual(called, [])

    def test_version_mismatch_is_rejected_before_client_construction(self):
        tracker = types.SimpleNamespace()
        mlflow = types.SimpleNamespace(__version__="3.15.0")
        original = importlib.import_module

        def fake_import(name, package=None):
            if name == ".tracking":
                return self.module
            if name == "mlflow":
                return mlflow
            if name == "mlflow.tracking":
                return tracker
            return original(name, package)

        with patch.object(delivery.importlib, "import_module", side_effect=fake_import):
            with self.assertRaises(delivery.DeliveryError) as raised:
                delivery.deliver(self.event, self.database, self.artifacts)
        self.assertEqual(raised.exception.code, "unsupported_mlflow_version")

    def test_existing_experiment_must_use_exact_local_artifact_root(self):
        self.client = FakeClient(f"sqlite:///{self.database}")
        self.client.install_experiment((self.root / "other").as_uri())
        with self.assertRaises(delivery.DeliveryError) as raised:
            self.send()
        self.assertEqual(raised.exception.code, "experiment_artifact_location_conflict")
        self.assertEqual(self.client.runs, {})

    def test_symlink_database_parent_and_nonabsolute_locations_are_rejected(self):
        link = self.root / "linked"
        link.symlink_to(self.root, target_is_directory=True)
        for database in (link / "tracking.db", Path("tracking.db")):
            with self.subTest(database=database):
                with self.assertRaises(delivery.DeliveryError):
                    delivery.deliver(
                        self.event, database, self.artifacts, client_factory=self.factory
                    )

    def test_sqlite_uri_metacharacters_and_controls_rejected_before_sdk_factory(self):
        for character in ("?", "#", "%", "\x00", "\n", "\x7f", "\x85"):
            with self.subTest(character=repr(character)):
                called = []
                database = self.root / f"tracking{character}.db"
                with self.assertRaises(delivery.DeliveryError) as raised:
                    delivery.deliver(
                        self.event,
                        database,
                        self.artifacts,
                        client_factory=lambda uri: called.append(uri),
                    )
                self.assertEqual(raised.exception.code, "unsafe_database_path")
                self.assertEqual(called, [])

    def test_cli_failure_is_one_sanitized_json_receipt_on_stdout(self):
        stdin = types.SimpleNamespace(buffer=io.BytesIO(b"{bad json"))
        stdout_bytes = io.BytesIO()
        stdout = types.SimpleNamespace(buffer=stdout_bytes)
        with patch.object(delivery.sys, "stdin", stdin), patch.object(
            delivery.sys, "stdout", stdout
        ):
            status = delivery.main(
                ["--database", str(self.database), "--artifacts-root", str(self.artifacts)]
            )
        self.assertEqual(status, 1)
        result = json.loads(stdout_bytes.getvalue())
        self.assertEqual(result["tracking_status"], "pending")
        self.assertEqual(result["failure_code"], "invalid_event")
        self.assertNotIn("bad json", stdout_bytes.getvalue().decode())

    @staticmethod
    def digest(event):
        data = json.dumps(
            event, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")
        ).encode()
        return hashlib.sha256(data).hexdigest()


if __name__ == "__main__":
    unittest.main()
