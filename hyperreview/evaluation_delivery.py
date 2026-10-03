"""Deliver one sanitized deterministic evaluation to local MLflow.

This subset creates a fresh run for every invocation. It does not implement
retry idempotency or recovery; a failure after run creation can leave a partial
local run and a regenerated local report bundle.
"""

import argparse
import hashlib
import importlib
import importlib.metadata
import os
from pathlib import Path
import re
import sys
import tempfile

from .evaluation_report import (
    ASSESSOR_TYPE,
    EVIDENTLY_VERSION,
    MAX_INPUT_BYTES,
    MAX_OUTPUT_BYTES,
    METRIC_DEFINITION_VERSION,
    METRIC_FIELDS,
    EvaluationReportError,
    _assessment_from_path,
    _encoded,
    create_report,
    validate_assessment,
)


MLFLOW_VERSION = "3.16.1"
EXPERIMENT_NAME = "HyperReview deterministic boundary evaluation v1"
RUN_NAME = "HyperReview deterministic boundary evaluation"
EVALUATION_STAGE = "evaluation_logged"
PENDING_STAGE = "pending"
REPORT_FILES = ("report.json", "report.html", "summary.json", "assessments.json")
_HEX_64 = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_RUN_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_MAX_SUMMARY_BYTES = 64 * 1024


class EvaluationDeliveryError(Exception):
    """A controlled local evaluation handoff failure."""

    def __init__(self, message, *, report_path=None):
        self.report_path = report_path
        super().__init__(message)


def _require(condition, message):
    if not condition:
        raise EvaluationDeliveryError(message)


def _trusted_path(value, *, directory, create=False, create_parent=False):
    try:
        path = Path(os.fspath(value))
    except (TypeError, ValueError, OSError) as error:
        raise EvaluationDeliveryError("Evaluation path is invalid") from error
    _require(path.is_absolute() and ".." not in path.parts,
             "Evaluation paths must be absolute and must not contain '..'")
    path = Path(os.path.abspath(path))
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current = current / component
        _require(not current.is_symlink(), "Evaluation paths must not traverse symlinks")
    if directory:
        if create:
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
        current = Path(path.anchor)
        for component in path.parts[1:]:
            current = current / component
            _require(not current.is_symlink(), "Evaluation paths must not traverse symlinks")
        _require(path.is_dir(), "Evaluation directory is unavailable")
        _require(path.stat().st_mode & 0o077 == 0,
                 "Evaluation directories must be private to the current user")
    else:
        if create_parent:
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            current = Path(path.anchor)
            for component in path.parts[1:]:
                current = current / component
                _require(not current.is_symlink(),
                         "Evaluation database path must not traverse symlinks")
        _require(path.parent.is_dir(), "Evaluation database parent is unavailable")
        _require(path.parent.stat().st_mode & 0o077 == 0,
                 "Evaluation database parent must be private to the current user")
        _require(not path.is_symlink() and (not path.exists() or path.is_file()),
                 "Evaluation database must be a regular, non-symlink file")
        for suffix in ("-wal", "-shm", "-journal"):
            _require(not Path(str(path) + suffix).is_symlink(),
                     "Evaluation SQLite sidecars must not be symlinks")
        if path.exists() and path.stat().st_size:
            try:
                with path.open("rb") as database_file:
                    signature = database_file.read(16)
            except OSError as error:
                raise EvaluationDeliveryError("Evaluation database cannot be inspected") from error
            _require(signature == b"SQLite format 3\x00",
                     "Evaluation database is not a SQLite file")
    return path


def _tracking_uri(database):
    return "sqlite:///" + database.as_posix()


def _load_client(uri, client_factory=None):
    if client_factory is not None:
        try:
            client = client_factory(uri)
        except Exception as error:
            raise EvaluationDeliveryError("Local MLflow client could not be created") from error
    else:
        try:
            installed_version = importlib.metadata.version("mlflow")
        except importlib.metadata.PackageNotFoundError as error:
            raise EvaluationDeliveryError("MLflow 3.16.1 is not installed") from error
        _require(installed_version == MLFLOW_VERSION,
                 "Evaluation delivery requires MLflow 3.16.1")
        try:
            os.environ["MLFLOW_TRACKING_URI"] = uri
            os.environ["MLFLOW_DISABLE_AGENT_HINT"] = "1"
            os.environ["MLFLOW_DISABLE_TELEMETRY"] = "1"
            os.environ["MLFLOW_ENABLE_ASYNC_LOGGING"] = "false"
            mlflow = importlib.import_module("mlflow")
            mlflow.set_tracking_uri(uri)
            client_type = importlib.import_module("mlflow.tracking").MlflowClient
            client = client_type(tracking_uri=uri)
        except Exception as error:
            raise EvaluationDeliveryError("Local MLflow 3.16.1 is unavailable") from error
    _require(getattr(client, "tracking_uri", None) == uri,
             "MLflow client tracking URI does not match the local SQLite database")
    return client


def _read_report_artifacts(report_path, assessment, report_output):
    path = _trusted_path(report_path, directory=True)
    _require(set(item.name for item in path.iterdir()) == set(REPORT_FILES),
             "Regenerated report bundle contains unexpected files")
    limits = {
        "report.json": MAX_OUTPUT_BYTES,
        "report.html": MAX_OUTPUT_BYTES,
        "summary.json": _MAX_SUMMARY_BYTES,
        "assessments.json": MAX_INPUT_BYTES,
    }
    artifacts = {}
    for name, limit in limits.items():
        artifact = path / name
        _require(not artifact.is_symlink() and artifact.is_file(),
                 "Regenerated report artifact is unavailable")
        _require(artifact.stat().st_size <= limit,
                 "Regenerated report artifact exceeds its size limit")
        try:
            with artifact.open("rb") as stream:
                body = stream.read(limit + 1)
        except OSError as error:
            raise EvaluationDeliveryError("Regenerated report artifact cannot be read") from error
        _require(len(body) <= limit, "Regenerated report artifact exceeds its size limit")
        artifacts[name] = body
    _require(artifacts["assessments.json"] == _encoded(assessment),
             "Regenerated assessment artifact does not match validated input")
    _require(artifacts["summary.json"] == _encoded(report_output["summary"]),
             "Regenerated report summary does not match its receipt")
    report_digest = hashlib.sha256(artifacts["report.json"]).hexdigest()
    _require(report_output.get("report_sha256") == report_digest,
             "Regenerated report fingerprint does not match")
    return artifacts


def _run_tags(assessment, artifacts):
    tags = {
        "hyperreview.evaluation_stage": PENDING_STAGE,
        "hyperreview.dataset_digest": assessment["dataset_digest"],
        "hyperreview.metric_definition_version": METRIC_DEFINITION_VERSION,
        "hyperreview.assessor_type": ASSESSOR_TYPE,
        "hyperreview.evidently_version": EVIDENTLY_VERSION,
    }
    fingerprints = {
        "report.json": "report_json",
        "report.html": "report_html",
        "summary.json": "summary",
        "assessments.json": "assessments",
    }
    for name, body in artifacts.items():
        stem = fingerprints[name]
        tags[f"hyperreview.{stem}_sha256"] = hashlib.sha256(body).hexdigest()
    return tags


def _verify_run_metadata(client, run_id, tags, metrics):
    try:
        run = client.get_run(run_id)
        recorded_tags = dict(getattr(getattr(run, "data", None), "tags", {}) or {})
    except Exception as error:
        raise EvaluationDeliveryError("Local evaluation metadata readback failed") from error
    _require(all(recorded_tags.get(key) == value for key, value in tags.items()),
             "Local evaluation metadata does not match the submitted values")
    for name, value in metrics.items():
        try:
            history = client.get_metric_history(run_id, name)
        except Exception as error:
            raise EvaluationDeliveryError("Local evaluation metric readback failed") from error
        _require(isinstance(history, list) and len(history) == 1
                 and getattr(history, "token", None) in (None, "")
                 and type(getattr(history[0], "value", None)) in (int, float)
                 and float(history[0].value) == float(value),
                 "Local evaluation metric does not match the submitted value")


def _verify_artifact_readback(client, run_id, artifacts):
    limits = {
        "report.json": MAX_OUTPUT_BYTES,
        "report.html": MAX_OUTPUT_BYTES,
        "summary.json": _MAX_SUMMARY_BYTES,
        "assessments.json": MAX_INPUT_BYTES,
    }
    try:
        entries = client.list_artifacts(run_id, path="evaluation")
    except Exception as error:
        raise EvaluationDeliveryError("Local evaluation artifact listing failed") from error
    expected_paths = {f"evaluation/{name}" for name in artifacts}
    actual_paths = {getattr(entry, "path", None) for entry in entries}
    _require(actual_paths == expected_paths
             and all(not getattr(entry, "is_dir", False) for entry in entries),
             "Local evaluation artifact listing does not match the submitted report")
    for name, expected_body in artifacts.items():
        try:
            downloaded = Path(client.download_artifacts(run_id, f"evaluation/{name}"))
            _require(not downloaded.is_symlink() and downloaded.is_file(),
                     "Downloaded evaluation artifact is not a regular local file")
            limit = limits[name]
            _require(downloaded.stat().st_size <= limit,
                     "Downloaded evaluation artifact exceeds its size limit")
            with downloaded.open("rb") as artifact_file:
                body = artifact_file.read(limit + 1)
        except EvaluationDeliveryError:
            raise
        except Exception as error:
            raise EvaluationDeliveryError("Local evaluation artifact readback failed") from error
        _require(len(body) <= limit
                 and hashlib.sha256(body).digest() == hashlib.sha256(expected_body).digest(),
                 "Local evaluation artifact fingerprint does not match")


def _metrics(assessment):
    metrics = {"case_count": len(assessment["records"])}
    for field in METRIC_FIELDS:
        values = [row[field] for row in assessment["records"] if row[field] is not None]
        metrics[f"coverage_{field}"] = len(values)
        if values:
            metrics[f"mean_{field}"] = sum(values) / len(values)
    return metrics


def _stage_run(client, assessment, report_output):
    client_uri = getattr(client, "tracking_uri", None)
    _require(type(client_uri) is str and client_uri.startswith("sqlite:////"),
             "MLflow must use a local SQLite tracking URI")
    artifact_uri = report_output["artifact_uri"]
    try:
        experiment = client.get_experiment_by_name(EXPERIMENT_NAME)
        if experiment is None:
            experiment_id = client.create_experiment(
                EXPERIMENT_NAME,
                artifact_location=artifact_uri,
                tags={"hyperreview.kind": "deterministic_boundary_evaluation"},
            )
            experiment = client.get_experiment(experiment_id)
        else:
            experiment_id = experiment.experiment_id
    except Exception as error:
        raise EvaluationDeliveryError("Local evaluation experiment could not be opened") from error
    _require(experiment is not None
             and str(experiment.experiment_id) == str(experiment_id),
             "Local evaluation experiment could not be confirmed")
    _require(getattr(experiment, "artifact_location", None) == artifact_uri,
             "Evaluation experiment artifact root does not match the trusted local root")

    artifacts = _read_report_artifacts(report_output["path"], assessment, report_output)
    tags = _run_tags(assessment, artifacts)
    metrics = _metrics(assessment)
    try:
        run = client.create_run(experiment_id, tags=tags, run_name=RUN_NAME)
    except Exception as error:
        raise EvaluationDeliveryError("Local evaluation run could not be created") from error
    run_id = getattr(getattr(run, "info", None), "run_id", None)
    _require(type(run_id) is str and _SAFE_RUN_ID.fullmatch(run_id) is not None,
             "MLflow returned an invalid evaluation run ID")

    try:
        for name, value in metrics.items():
            client.log_metric(run_id, name, float(value), synchronous=True)
        with tempfile.TemporaryDirectory(prefix="hyperreview-evaluation-artifacts-") as temporary:
            staging = Path(temporary)
            staging.chmod(0o700)
            for name, body in artifacts.items():
                staged = staging / name
                descriptor = os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "wb") as target:
                    target.write(body)
                client.log_artifact(run_id, str(staged), artifact_path="evaluation")
        _verify_run_metadata(client, run_id, tags, metrics)
        _verify_artifact_readback(client, run_id, artifacts)
        client.set_tag(run_id, "hyperreview.evaluation_stage", EVALUATION_STAGE)
        confirmed_tags = {**tags, "hyperreview.evaluation_stage": EVALUATION_STAGE}
        _verify_run_metadata(client, run_id, confirmed_tags, metrics)
        client.set_terminated(run_id, status="FINISHED")
        confirmed_run = client.get_run(run_id)
        status = getattr(getattr(confirmed_run, "info", None), "status", None)
        _require(getattr(status, "value", status) == "FINISHED",
                 "Local evaluation run did not reach a finished state")
    except Exception as error:
        try:
            client.set_tag(run_id, "hyperreview.evaluation_stage", PENDING_STAGE)
        except Exception:
            pass
        try:
            client.set_terminated(run_id, status="FAILED")
        except Exception:
            pass
        raise EvaluationDeliveryError("Local evaluation artifacts or metrics could not be confirmed") from error
    return run_id


def _deliver_evaluation(assessment, *, output_root, database, artifacts_root,
                        sdk_factory=None, mlflow_client_factory=None):
    """Regenerate and log sanitized deterministic evaluation artifacts locally.

    Each call creates a new MLflow run; this function does not provide retry
    idempotency or recovery if a local write fails partway through.
    ``sdk_factory`` and ``mlflow_client_factory`` are offline test seams.
    """
    try:
        assessment = validate_assessment(assessment)
    except EvaluationReportError as error:
        raise EvaluationDeliveryError("Evaluation assessment failed local validation") from error
    output_root = _trusted_path(output_root, directory=True, create=True)
    database = _trusted_path(database, directory=False, create_parent=True)
    _require(database.is_absolute(), "Evaluation database path must be absolute")
    _require(database.suffix in (".db", ".sqlite", ".sqlite3"),
             "Evaluation database must use a SQLite filename")
    artifacts_root = _trusted_path(artifacts_root, directory=True, create=True)
    uri = _tracking_uri(database)
    artifact_uri = artifacts_root.as_uri()

    # These settings are assigned before either SDK is imported, and the fixed
    # URI prevents inherited tracking configuration from selecting a server.
    os.environ["DO_NOT_TRACK"] = "1"
    os.environ["EVIDENTLY_DISABLE_TELEMETRY"] = "1"
    os.environ["MLFLOW_TRACKING_URI"] = uri
    os.environ["MLFLOW_DISABLE_AGENT_HINT"] = "1"
    os.environ["MLFLOW_DISABLE_TELEMETRY"] = "1"
    os.environ["MLFLOW_ENABLE_ASYNC_LOGGING"] = "false"

    try:
        report_output = create_report(assessment, output_root, sdk_factory=sdk_factory)
    except EvaluationReportError as error:
        raise EvaluationDeliveryError("Local evaluation report generation failed") from error
    _require(type(report_output) is dict
             and set(report_output) == {"path", "summary", "report_sha256"},
             "Local evaluation report returned an invalid result")
    report_output = {**report_output, "artifact_uri": artifact_uri}
    try:
        client = _load_client(uri, mlflow_client_factory)
        run_id = _stage_run(client, assessment, report_output)
    except EvaluationDeliveryError as error:
        raise EvaluationDeliveryError(str(error), report_path=report_output["path"]) from error
    return {
        "report_path": report_output["path"],
        "run_id": run_id,
        "evaluation_stage": EVALUATION_STAGE,
        "dataset_digest": assessment["dataset_digest"],
    }


def deliver_evaluation(assessment, *, output_root, database, artifacts_root,
                       sdk_factory=None, mlflow_client_factory=None):
    """Regenerate and deliver sanitized assessment metadata to local MLflow.

    Each call creates a new run; retry idempotency and recovery are not
    implemented. A partial failure may leave a local report or failed run.
    The two optional factories are offline test seams.
    """
    try:
        return _deliver_evaluation(
            assessment,
            output_root=output_root,
            database=database,
            artifacts_root=artifacts_root,
            sdk_factory=sdk_factory,
            mlflow_client_factory=mlflow_client_factory,
        )
    except EvaluationDeliveryError:
        raise
    except Exception:
        raise EvaluationDeliveryError("Local evaluation delivery did not complete") from None


def main(argv=None):
    parser = argparse.ArgumentParser(description="Deliver a deterministic evaluation to local MLflow.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--artifacts-root", required=True, type=Path)
    args = parser.parse_args(argv)
    paths = (args.input, args.output_root, args.database, args.artifacts_root)
    if any(not path.is_absolute() for path in paths):
        print("HyperReview: all evaluation paths must be absolute", file=sys.stderr)
        return 2
    try:
        assessment = _assessment_from_path(args.input)
        result = deliver_evaluation(
            assessment,
            output_root=args.output_root,
            database=args.database,
            artifacts_root=args.artifacts_root,
        )
    except (EvaluationDeliveryError, EvaluationReportError, OSError, ValueError) as error:
        print(f"HyperReview: {error}; evaluation delivery did not complete", file=sys.stderr)
        if isinstance(error, EvaluationDeliveryError) and error.report_path is not None:
            print(f"Local report bundle: {error.report_path}", file=sys.stderr)
        print("No model inference was performed", file=sys.stderr)
        return 1
    print(f"Evaluation report: {result['report_path']}")
    print(f"MLflow evaluation run: {result['run_id']}")
    print("Stage: evaluation_logged; human evaluation remains pending")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
