import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from hyperreview.evaluation_delivery import (
    EVALUATION_STAGE,
    EXPERIMENT_NAME,
    MLFLOW_VERSION,
    EvaluationDeliveryError,
    _load_client,
    deliver_evaluation,
    main,
)
from hyperreview.evaluation_report import (
    ASSESSOR_TYPE,
    EVIDENTLY_VERSION,
    INPUT_SCHEMA,
    METRIC_DEFINITION_VERSION,
    METRIC_FIELDS,
)


def valid_assessment(*, structural_change_count=2):
    records = []
    for index in range(5):
        records.append({
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
        "records": records,
    }


class FakeReportSDK:
    def __init__(self):
        self.rows = None
        self.columns = None

    def __call__(self, rows, columns):
        self.rows = rows
        self.columns = columns
        return {
            "sdk_version": EVIDENTLY_VERSION,
            "report_json": b'{"numeric_metrics":{"case_count":5}}',
            "report_html": b"<html><body>fixed numeric report</body></html>",
        }


class Value:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class PagedList(list):
    token = None


class FakeMLflowClient:
    def __init__(self, uri, artifact_store):
        self.tracking_uri = uri
        self.artifact_store = Path(artifact_store)
        self.experiment = None
        self.experiment_name = None
        self.experiment_create_tags = None
        self.run = None
        self.run_name = None
        self.metrics = {}
        self.artifacts = {}
        self.missing_metric = None
        self.metric_page_token = None
        self.artifact_mutations = {}
        self.terminated_status = None

    def get_experiment_by_name(self, _name):
        return self.experiment

    def create_experiment(self, name, artifact_location, tags):
        self.experiment_name = name
        self.experiment_create_tags = tags
        self.experiment = Value(experiment_id="eval-1", artifact_location=artifact_location,
                                name=name)
        return self.experiment.experiment_id

    def get_experiment(self, _experiment_id):
        return self.experiment

    def create_run(self, experiment_id, tags, run_name):
        self.run_name = run_name
        self.run = Value(info=Value(run_id="run-evaluation-1", experiment_id=experiment_id),
                         data=Value(tags=dict(tags)), info_status="RUNNING")
        self.run.info.status = "RUNNING"
        return self.run

    def log_metric(self, run_id, key, value, *, synchronous):
        assert run_id == self.run.info.run_id
        assert synchronous is True
        self.metrics[key] = [Value(value=value)]

    def log_artifact(self, run_id, local_path, *, artifact_path):
        assert run_id == self.run.info.run_id
        name = Path(local_path).name
        destination = self.artifact_store / artifact_path / name
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        body = Path(local_path).read_bytes()
        destination.write_bytes(body)
        self.artifacts[f"{artifact_path}/{name}"] = body

    def get_run(self, run_id):
        assert run_id == self.run.info.run_id
        return self.run

    def get_metric_history(self, run_id, name):
        assert run_id == self.run.info.run_id
        if name == self.missing_metric:
            history = PagedList()
        else:
            history = PagedList(self.metrics.get(name, []))
        history.token = self.metric_page_token
        return history

    def set_tag(self, run_id, key, value):
        assert run_id == self.run.info.run_id
        self.run.data.tags[key] = value

    def list_artifacts(self, run_id, *, path):
        assert run_id == self.run.info.run_id
        return [Value(path=name, is_dir=False) for name in sorted(self.artifacts)]

    def download_artifacts(self, run_id, path):
        assert run_id == self.run.info.run_id
        self.assert_path = path
        relative_name = path.removeprefix("evaluation/")
        target = self.artifact_store / path
        if relative_name in self.artifact_mutations:
            target.write_bytes(self.artifact_mutations[relative_name])
        return str(target)

    def set_terminated(self, run_id, *, status):
        assert run_id == self.run.info.run_id
        self.terminated_status = status
        self.run.info.status = status


class EvaluationDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="evaluation-delivery-test-")
        self.root = Path(self.temporary.name).resolve()
        self.output_root = self.root / "reports"
        self.database = self.root / "mlflow" / "tracking.sqlite"
        self.artifacts_root = self.root / "mlflow" / "artifacts"
        self.sdk = FakeReportSDK()
        self.client = FakeMLflowClient("sqlite:///" + self.database.as_posix(),
                                       self.root / "mlflow-artifact-store")

    def tearDown(self):
        self.temporary.cleanup()

    def deliver(self, assessment=None):
        return deliver_evaluation(
            valid_assessment() if assessment is None else assessment,
            output_root=self.output_root,
            database=self.database,
            artifacts_root=self.artifacts_root,
            sdk_factory=self.sdk,
            mlflow_client_factory=lambda uri: self.client,
        )

    def test_regenerates_report_and_logs_only_sanitized_artifacts_metrics_and_tags(self):
        result = self.deliver()
        self.assertEqual(result["evaluation_stage"], EVALUATION_STAGE)
        self.assertEqual(result["run_id"], "run-evaluation-1")
        self.assertTrue(Path(result["report_path"]).is_dir())
        self.assertEqual(self.client.experiment_name, EXPERIMENT_NAME)
        self.assertEqual(self.client.experiment.artifact_location, self.artifacts_root.as_uri())
        self.assertEqual(self.client.tracking_uri, "sqlite:///" + self.database.as_posix())
        self.assertEqual(self.client.terminated_status, "FINISHED")
        self.assertEqual(self.client.run.data.tags["hyperreview.evaluation_stage"],
                         EVALUATION_STAGE)

        self.assertEqual(set(self.client.artifacts), {
            "evaluation/report.json", "evaluation/report.html",
            "evaluation/summary.json", "evaluation/assessments.json",
        })
        self.assertEqual(self.client.artifacts["evaluation/report.json"],
                         b'{"numeric_metrics":{"case_count":5}}')
        saved_assessment = json.loads(self.client.artifacts["evaluation/assessments.json"])
        self.assertEqual(saved_assessment["dataset_digest"], "a" * 64)
        self.assertEqual(set(self.sdk.columns), set(METRIC_FIELDS))
        self.assertTrue(all("case_id" not in row for row in self.sdk.rows))

        expected_metrics = {
            "case_count",
            *(f"coverage_{field}" for field in METRIC_FIELDS),
            *(f"mean_{field}" for field in METRIC_FIELDS),
        }
        self.assertEqual(set(self.client.metrics), expected_metrics)
        self.assertEqual(self.client.metrics["case_count"][0].value, 5.0)
        self.assertEqual(self.client.metrics["mean_structural_change_count"][0].value, 2.0)
        tags = self.client.run.data.tags
        self.assertEqual(tags["hyperreview.dataset_digest"], "a" * 64)
        self.assertEqual(tags["hyperreview.metric_definition_version"], METRIC_DEFINITION_VERSION)
        self.assertEqual(tags["hyperreview.assessor_type"], ASSESSOR_TYPE)
        self.assertEqual(tags["hyperreview.report_json_sha256"],
                         hashlib.sha256(self.client.artifacts["evaluation/report.json"]).hexdigest())
        self.assertEqual(tags["hyperreview.report_html_sha256"],
                         hashlib.sha256(self.client.artifacts["evaluation/report.html"]).hexdigest())
        self.assertEqual(tags["hyperreview.summary_sha256"],
                         hashlib.sha256(self.client.artifacts["evaluation/summary.json"]).hexdigest())
        self.assertEqual(tags["hyperreview.assessments_sha256"],
                         hashlib.sha256(self.client.artifacts["evaluation/assessments.json"]).hexdigest())
        self.assertNotIn("source", json.dumps(tags))
        self.assertNotIn("model", json.dumps(tags))
        self.assertNotIn("case_id", self.client.metrics)

    def test_missing_change_counts_are_not_logged_as_zero(self):
        self.deliver(valid_assessment(structural_change_count=None))
        self.assertNotIn("mean_structural_change_count", self.client.metrics)
        self.assertEqual(self.client.metrics["case_count"][0].value, 5.0)
        self.assertEqual(self.client.metrics["coverage_structural_change_count"][0].value, 0.0)

    def test_invalid_assessment_fails_before_report_or_client_initialization(self):
        bad = valid_assessment()
        bad["source_text"] = "private source sentinel"
        client_factory = mock.Mock()
        with self.assertRaisesRegex(EvaluationDeliveryError, "assessment failed"):
            deliver_evaluation(bad, output_root=self.output_root, database=self.database,
                               artifacts_root=self.artifacts_root, sdk_factory=self.sdk,
                               mlflow_client_factory=client_factory)
        self.assertIsNone(self.sdk.rows)
        client_factory.assert_not_called()

    def test_report_generation_failure_does_not_create_mlflow_client(self):
        client_factory = mock.Mock()

        def fail_report(_rows, _columns):
            raise RuntimeError("private report error")

        with self.assertRaisesRegex(EvaluationDeliveryError, "report generation failed"):
            deliver_evaluation(valid_assessment(), output_root=self.output_root,
                               database=self.database, artifacts_root=self.artifacts_root,
                               sdk_factory=fail_report,
                               mlflow_client_factory=client_factory)
        client_factory.assert_not_called()

    def test_rejects_symlinked_and_non_sqlite_trusted_paths(self):
        actual = self.root / "actual"
        actual.mkdir()
        link = self.root / "linked"
        link.symlink_to(actual, target_is_directory=True)
        with self.assertRaisesRegex(EvaluationDeliveryError, "symlinks"):
            deliver_evaluation(valid_assessment(), output_root=self.output_root,
                               database=self.database, artifacts_root=link,
                               sdk_factory=self.sdk, mlflow_client_factory=lambda _uri: self.client)

        bad_db = self.root / "mlflow" / "not-a-db.sqlite"
        bad_db.parent.mkdir(mode=0o700, exist_ok=True)
        bad_db.write_text("not sqlite", encoding="utf-8")
        with self.assertRaisesRegex(EvaluationDeliveryError, "SQLite"):
            deliver_evaluation(valid_assessment(), output_root=self.output_root,
                               database=bad_db, artifacts_root=self.artifacts_root,
                               sdk_factory=self.sdk, mlflow_client_factory=lambda _uri: self.client)

    def test_existing_experiment_must_use_exact_artifact_root(self):
        self.client.experiment = Value(experiment_id="eval-old", artifact_location="file:///wrong",
                                       name=EXPERIMENT_NAME)
        with self.assertRaisesRegex(EvaluationDeliveryError, "artifact root"):
            self.deliver()

    def test_missing_metric_readback_keeps_stage_pending_and_marks_run_failed(self):
        self.client.missing_metric = "mean_projection_grammar_valid"
        with self.assertRaisesRegex(EvaluationDeliveryError, "could not be confirmed"):
            self.deliver()
        self.assertEqual(self.client.run.data.tags["hyperreview.evaluation_stage"], "pending")
        self.assertEqual(self.client.terminated_status, "FAILED")

    def test_metric_paged_list_accepts_empty_token_and_rejects_more_pages(self):
        result = self.deliver()
        self.assertEqual(result["evaluation_stage"], EVALUATION_STAGE)

        other = FakeMLflowClient(self.client.tracking_uri, self.root / "paged-artifact-store")
        other.metric_page_token = "next-page"
        with self.assertRaisesRegex(EvaluationDeliveryError, "could not be confirmed"):
            deliver_evaluation(valid_assessment(), output_root=self.output_root,
                               database=self.database, artifacts_root=self.artifacts_root,
                               sdk_factory=FakeReportSDK(), mlflow_client_factory=lambda _uri: other)
        self.assertEqual(other.run.data.tags["hyperreview.evaluation_stage"], "pending")
        self.assertEqual(other.terminated_status, "FAILED")

    def test_artifact_fingerprint_mismatch_keeps_stage_pending_and_marks_run_failed(self):
        self.client.artifact_mutations["report.html"] = b"mismatched artifact"
        with self.assertRaisesRegex(EvaluationDeliveryError, "could not be confirmed"):
            self.deliver()
        self.assertEqual(self.client.run.data.tags["hyperreview.evaluation_stage"], "pending")
        self.assertEqual(self.client.terminated_status, "FAILED")

    def test_default_mlflow_loader_requires_exact_installed_version(self):
        with mock.patch("hyperreview.evaluation_delivery.importlib.metadata.version",
                        return_value="3.16.0"), \
             mock.patch("hyperreview.evaluation_delivery.importlib.import_module") as importer:
            with self.assertRaisesRegex(EvaluationDeliveryError, "MLflow 3.16.1"):
                _load_client("sqlite:////tmp/evaluation.sqlite")
        importer.assert_not_called()
        self.assertEqual(MLFLOW_VERSION, "3.16.1")

    def test_cli_rejects_relative_paths_without_loading_input(self):
        self.assertEqual(main(["--input", "relative.json", "--output-root", "/tmp/out",
                              "--database", "/tmp/tracking.sqlite",
                              "--artifacts-root", "/tmp/artifacts"]), 2)


if __name__ == "__main__":
    unittest.main()
