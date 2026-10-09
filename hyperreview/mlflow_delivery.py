"""Deliver one sanitized HyperReview tracking event to a local MLflow store.

This module is independent of MLflow at import time. The SDK is loaded only by
deliver(), after event and filesystem validation.
"""

import argparse
import hashlib
import importlib
import json
import os
import re
import sys
from pathlib import Path
from uuid import UUID


EVENT_SCHEMA = "hyperreview.tracking-event.v1"
RECEIPT_SCHEMA = "hyperreview.tracking-receipt.v1"
MLFLOW_VERSION = "3.16.1"
EXPERIMENT_NAME = "HyperReview manual preview v1"
MAX_EVENT_BYTES = 64 * 1024
MAX_RECEIPT_BYTES = 64 * 1024
_METADATA_FIELDS = frozenset(
    {
        "repository",
        "pr",
        "merge_base_sha",
        "head_sha",
        "evidence_digest",
        "request_digest",
        "result_digest",
        "abstraction_profile",
        "prompt_version",
        "reviewer_profile_version",
        "reviewer_profile_sha256",
        "provider",
        "model_identity_sha256",
        "compiler_sha256",
        "compiler_resolver_name",
        "compiler_resolver_version",
        "delivery_mode",
    }
)
_STAGE_NAMES = frozenset({"collection", "inference", "projection_validation", "rendering"})
_METRIC_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_STAGE_FIELDS = frozenset({"name", "status", "elapsed_ms"})
_EVENT_FIELDS = frozenset(
    {"schema", "correlation_id", "attempt", "metadata", "metrics", "stages"}
)
_RECEIPT_FIELDS = frozenset(
    {
        "schema",
        "correlation_id",
        "attempt",
        "tracking_status",
        "experiment_id",
        "run_id",
        "trace_id",
        "event_digest",
    }
)


class DeliveryError(Exception):
    """A controlled failure that is safe to serialize as a machine receipt."""

    def __init__(self, code, correlation_id=None, attempt=None):
        self.code = code
        self.correlation_id = correlation_id
        self.attempt = attempt
        super().__init__(code)

    def as_receipt(self):
        return {
            "schema": RECEIPT_SCHEMA,
            "correlation_id": self.correlation_id,
            "attempt": self.attempt,
            "tracking_status": "pending",
            "experiment_id": None,
            "run_id": None,
            "trace_id": None,
            "event_digest": None,
            "failure_code": self.code,
        }


def _canonical_bytes(value):
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _canonical_digest(event):
    return hashlib.sha256(_canonical_bytes(event)).hexdigest()


def _safe_event(event):
    """Run the owning tracking contract validator, then enforce its wire shape."""
    try:
        validator = importlib.import_module(".tracking", __package__).validate_event
        checked = validator(event)
    except Exception:
        raise DeliveryError("invalid_event") from None
    checked = event if checked is None else checked
    if type(checked) is not dict or set(checked) != _EVENT_FIELDS:
        raise DeliveryError("invalid_event")
    if checked.get("schema") != EVENT_SCHEMA:
        raise DeliveryError("invalid_event")

    correlation_id = checked.get("correlation_id")
    if type(correlation_id) is not str:
        raise DeliveryError("invalid_event")
    try:
        UUID(correlation_id)
    except (ValueError, AttributeError):
        raise DeliveryError("invalid_event") from None
    attempt = checked.get("attempt")
    if type(attempt) is not int or attempt < 1:
        raise DeliveryError("invalid_event", correlation_id)

    metadata = checked.get("metadata")
    if type(metadata) is not dict or set(metadata) != _METADATA_FIELDS:
        raise DeliveryError("invalid_event", correlation_id, attempt)
    for value in metadata.values():
        if type(value) is not str or not value or len(value) > 512:
            raise DeliveryError("invalid_event", correlation_id, attempt)
        if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
            raise DeliveryError("invalid_event", correlation_id, attempt)

    metrics = checked.get("metrics")
    if type(metrics) is not dict:
        raise DeliveryError("invalid_event", correlation_id, attempt)
    for name, value in metrics.items():
        if type(name) is not str or not _METRIC_NAME.fullmatch(name):
            raise DeliveryError("invalid_event", correlation_id, attempt)
        if type(value) is not int or value < 0:
            raise DeliveryError("invalid_event", correlation_id, attempt)

    stages = checked.get("stages")
    if type(stages) is not list:
        raise DeliveryError("invalid_event", correlation_id, attempt)
    seen_stages = set()
    for stage in stages:
        if type(stage) is not dict or set(stage) != _STAGE_FIELDS:
            raise DeliveryError("invalid_event", correlation_id, attempt)
        name = stage.get("name")
        status = stage.get("status")
        elapsed = stage.get("elapsed_ms")
        if type(name) is not str or name not in _STAGE_NAMES or name in seen_stages:
            raise DeliveryError("invalid_event", correlation_id, attempt)
        if type(status) is not str or status not in {"completed", "unavailable"}:
            raise DeliveryError("invalid_event", correlation_id, attempt)
        if elapsed is not None and (type(elapsed) is not int or elapsed < 0):
            raise DeliveryError("invalid_event", correlation_id, attempt)
        if status == "unavailable" and elapsed is not None:
            raise DeliveryError("invalid_event", correlation_id, attempt)
        seen_stages.add(name)
    return checked


def _absolute_path(value, *, is_directory, code, reject_uri_chars=False):
    try:
        path_value = os.fspath(value)
        if reject_uri_chars:
            if type(path_value) is not str or any(
                char in "?#%" or ord(char) < 0x20 or 0x7F <= ord(char) <= 0x9F
                for char in path_value
            ):
                raise DeliveryError(code)
        raw = Path(path_value)
    except DeliveryError:
        raise
    except (TypeError, ValueError, OSError):
        raise DeliveryError(code) from None
    if not raw.is_absolute() or ".." in raw.parts:
        raise DeliveryError(code)
    path = Path(os.path.abspath(raw))
    # Check lexical components before resolving so a symlink cannot be hidden by
    # Path.resolve(). The database leaf may be created by the local SDK.
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        if current.is_symlink():
            raise DeliveryError(code)
    if is_directory:
        if not path.exists() or not path.is_dir():
            raise DeliveryError(code)
    else:
        if (
            not path.parent.exists()
            or not path.parent.is_dir()
            or (path.exists() and not path.is_file())
        ):
            raise DeliveryError(code)
    return path


def _tracking_uri(database):
    # An absolute path begins with '/', yielding SQLAlchemy's sqlite://// URI.
    return "sqlite:///" + database.as_posix()


def _load_client(uri, client_factory):
    if client_factory is not None:
        return client_factory(uri)
    try:
        os.environ["MLFLOW_DISABLE_AGENT_HINT"] = "1"
        mlflow = importlib.import_module("mlflow")
        if getattr(mlflow, "__version__", None) != MLFLOW_VERSION:
            raise DeliveryError("unsupported_mlflow_version")
        # start_trace uses MLflow's process-global trace provider. Set the exact
        # local URI before client construction so run and trace writes agree.
        mlflow.set_tracking_uri(uri)
        client_class = importlib.import_module("mlflow.tracking").MlflowClient
        client = client_class(uri)
    except DeliveryError:
        raise
    except Exception:
        raise DeliveryError("mlflow_unavailable") from None
    if getattr(client, "tracking_uri", None) != uri:
        raise DeliveryError("tracking_uri_mismatch")
    return client


def _pages(fetch, *, page_size, correlation_id, attempt):
    token = None
    seen_tokens = set()
    for _ in range(10000):
        page = fetch(token, page_size)
        yield from page
        token = getattr(page, "token", None)
        if not token:
            return
        if token in seen_tokens:
            raise DeliveryError("pagination_conflict", correlation_id, attempt)
        seen_tokens.add(token)
    raise DeliveryError("pagination_limit", correlation_id, attempt)


def _find_runs(client, experiment_id, correlation_id, attempt):
    filter_string = (
        f"tags.hyperreview_correlation_id = '{correlation_id}' AND "
        f"tags.hyperreview_attempt = '{attempt}'"
    )
    try:
        matches = list(
            _pages(
                lambda token, size: client.search_runs(
                    [experiment_id],
                    filter_string=filter_string,
                    run_view_type=3,
                    max_results=size,
                    page_token=token,
                ),
                page_size=1000,
                correlation_id=correlation_id,
                attempt=attempt,
            )
        )
    except DeliveryError:
        raise
    except Exception:
        raise DeliveryError("run_search_failed", correlation_id, attempt) from None
    if len(matches) > 1:
        raise DeliveryError("run_conflict", correlation_id, attempt)
    return matches[0] if matches else None


def _find_traces(client, experiment_id, correlation_id, attempt):
    filter_string = (
        f"tags.hyperreview_correlation_id = '{correlation_id}' AND "
        f"tags.hyperreview_attempt = '{attempt}'"
    )
    try:
        matches = list(
            _pages(
                lambda token, size: client.search_traces(
                    locations=[experiment_id],
                    filter_string=filter_string,
                    max_results=size,
                    page_token=token,
                    include_spans=False,
                    flush=True,
                ),
                page_size=100,
                correlation_id=correlation_id,
                attempt=attempt,
            )
        )
    except DeliveryError:
        raise
    except Exception:
        raise DeliveryError("trace_search_failed", correlation_id, attempt) from None
    if len(matches) > 1:
        raise DeliveryError("trace_conflict", correlation_id, attempt)
    return matches[0] if matches else None


def _run_id(run):
    return getattr(getattr(run, "info", None), "run_id", None)


def _run_tags(run):
    return dict(getattr(getattr(run, "data", None), "tags", {}) or {})


def _trace_info(trace):
    return getattr(trace, "info", trace)


def _trace_id(trace):
    return getattr(_trace_info(trace), "trace_id", None)


def _get_trace_tags(trace):
    return dict(getattr(_trace_info(trace), "tags", {}) or {})


def _trace_status(trace):
    status = getattr(_trace_info(trace), "status", None)
    return getattr(status, "value", status)


def _ensure_run_tags(client, run, expected, correlation_id, attempt):
    run_id = _run_id(run)
    if not run_id:
        raise DeliveryError("run_identity_missing", correlation_id, attempt)
    current = _run_tags(run)
    for key, value in expected.items():
        if key in current:
            if current[key] != value:
                raise DeliveryError("run_metadata_conflict", correlation_id, attempt)
            continue
        try:
            client.set_tag(run_id, key, value, synchronous=True)
        except Exception:
            raise DeliveryError("run_tag_write_failed", correlation_id, attempt) from None
    try:
        refreshed = client.get_run(run_id)
    except Exception:
        raise DeliveryError("run_readback_failed", correlation_id, attempt) from None
    tags = _run_tags(refreshed)
    if any(tags.get(key) != value for key, value in expected.items()):
        raise DeliveryError("run_metadata_conflict", correlation_id, attempt)
    return refreshed


def _ensure_metrics(client, run_id, metrics, correlation_id, attempt):
    for name, value in metrics.items():
        try:
            history = client.get_metric_history(run_id, name)
        except Exception:
            raise DeliveryError("metric_readback_failed", correlation_id, attempt) from None
        values = [getattr(entry, "value", None) for entry in history]
        if values and any(float(item) != float(value) for item in values):
            raise DeliveryError("metric_conflict", correlation_id, attempt)
        if not values:
            try:
                client.log_metric(run_id, name, value, synchronous=True)
            except Exception:
                raise DeliveryError("metric_write_failed", correlation_id, attempt) from None
        try:
            confirmed = client.get_metric_history(run_id, name)
        except Exception:
            raise DeliveryError("metric_readback_failed", correlation_id, attempt) from None
        if not confirmed or any(float(item.value) != float(value) for item in confirmed):
            raise DeliveryError("metric_conflict", correlation_id, attempt)


def _trace_attributes(event):
    attributes = {f"hyperreview.{key}": value for key, value in event["metadata"].items()}
    attributes.update(
        {f"hyperreview.metric.{key}": value for key, value in event["metrics"].items()}
    )
    attributes["hyperreview.recording_mode"] = "retrospective_receipt"
    return attributes


def _trace_tags(correlation_id, attempt, digest):
    return {
        "hyperreview_correlation_id": correlation_id,
        "hyperreview_attempt": str(attempt),
        "hyperreview_event_digest": digest,
    }


def _verify_trace(client, trace, experiment_id, run_id, correlation_id, attempt, digest, stages):
    trace_id = _trace_id(trace)
    status = _trace_status(trace)
    if not trace_id:
        raise DeliveryError("trace_identity_missing", correlation_id, attempt)
    if status in {"IN_PROGRESS", "STATE_UNSPECIFIED", "TRACE_STATUS_UNSPECIFIED", None}:
        raise DeliveryError("incomplete_trace", correlation_id, attempt)
    if status != "OK":
        raise DeliveryError(
            "trace_error" if status == "ERROR" else "incomplete_trace",
            correlation_id,
            attempt,
        )
    expected = _trace_tags(correlation_id, attempt, digest)
    tags = _get_trace_tags(trace)
    if any(tags.get(key) != value for key, value in expected.items()):
        try:
            trace = client.get_trace(trace_id, flush=True)
        except Exception:
            raise DeliveryError("trace_readback_failed", correlation_id, attempt) from None
        if any(_get_trace_tags(trace).get(key) != value for key, value in expected.items()):
            raise DeliveryError("trace_metadata_conflict", correlation_id, attempt)
        status = _trace_status(trace)
        if status != "OK":
            raise DeliveryError(
                "trace_error" if status == "ERROR" else "incomplete_trace",
                correlation_id,
                attempt,
            )
    info = _trace_info(trace)
    location = getattr(info, "trace_location", None)
    exp_from_location = getattr(getattr(location, "mlflow_experiment", None), "experiment_id", None)
    exp_id = getattr(info, "experiment_id", None) or exp_from_location
    if exp_id is not None and str(exp_id) != str(experiment_id):
        raise DeliveryError("trace_location_conflict", correlation_id, attempt)
    trace_metadata = getattr(info, "trace_metadata", {}) or {}
    if trace_metadata.get("mlflow.sourceRun") != run_id:
        raise DeliveryError("trace_run_link_conflict", correlation_id, attempt)
    try:
        full = client.get_trace(trace_id, flush=True)
    except Exception:
        raise DeliveryError("trace_readback_failed", correlation_id, attempt) from None
    spans = getattr(getattr(full, "data", None), "spans", None)
    if spans is not None and not spans:
        raise DeliveryError("trace_spans_missing", correlation_id, attempt)
    if spans is not None:
        names = [getattr(span, "name", None) for span in spans]
        expected_names = [
            "hyperreview.preview.receipt_export",
            *(stage["name"] for stage in stages),
        ]
        if names != expected_names:
            raise DeliveryError("trace_spans_conflict", correlation_id, attempt)
    return trace_id


def _create_trace(client, event, experiment_id, run_id, digest):
    correlation_id = event["correlation_id"]
    attempt = event["attempt"]
    try:
        root = client.start_trace(
            "hyperreview.preview.receipt_export",
            span_type="CHAIN",
            inputs=None,
            attributes=_trace_attributes(event),
            tags=_trace_tags(correlation_id, attempt, digest),
            experiment_id=experiment_id,
            run_id=run_id,
        )
        trace_id = getattr(root, "trace_id", None)
        root_span_id = getattr(root, "span_id", None)
        recording = getattr(root, "is_recording", None)
        if not trace_id or not root_span_id or (callable(recording) and not recording()):
            raise DeliveryError("trace_start_failed", correlation_id, attempt)
        for stage in event["stages"]:
            attrs = {"stage_status": stage["status"]}
            if stage["elapsed_ms"] is not None:
                attrs["recorded_elapsed_ms"] = stage["elapsed_ms"]
            child = client.start_span(
                stage["name"],
                trace_id=trace_id,
                parent_id=root_span_id,
                span_type="CHAIN",
                inputs=None,
                attributes=attrs,
            )
            child_id = getattr(child, "span_id", None)
            if not child_id:
                raise DeliveryError("trace_span_start_failed", correlation_id, attempt)
            client.end_span(trace_id, child_id, outputs=None, status="OK")
        client.end_trace(
            trace_id,
            outputs=None,
            attributes={"hyperreview.recording_mode": "retrospective_receipt"},
            status="OK",
        )
    except DeliveryError:
        raise
    except Exception:
        raise DeliveryError("trace_write_failed", correlation_id, attempt) from None
    # Submit then search with flush so a receipt requires a final readable trace.
    trace = _find_traces(client, experiment_id, correlation_id, attempt)
    if trace is None:
        raise DeliveryError("trace_not_confirmed", correlation_id, attempt)
    return _verify_trace(
        client, trace, experiment_id, run_id, correlation_id, attempt, digest, event["stages"]
    )


def _receipt(event, experiment_id, run_id, trace_id, digest):
    result = {
        "schema": RECEIPT_SCHEMA,
        "correlation_id": event["correlation_id"],
        "attempt": event["attempt"],
        "tracking_status": "confirmed",
        "experiment_id": str(experiment_id),
        "run_id": run_id,
        "trace_id": trace_id,
        "event_digest": digest,
    }
    if set(result) != _RECEIPT_FIELDS:
        raise DeliveryError("receipt_invalid", event["correlation_id"], event["attempt"])
    return result


def deliver(event, database, artifacts_root, client_factory=None):
    """Validate and idempotently deliver one sanitized event.

    client_factory is a fixture hook accepting the exact SQLite URI. Production
    callers omit it so the installed MLflow version is checked.
    """
    checked = _safe_event(event)
    correlation_id = checked["correlation_id"]
    attempt = checked["attempt"]
    try:
        database = _absolute_path(
            database,
            is_directory=False,
            code="unsafe_database_path",
            reject_uri_chars=True,
        )
        artifacts_root = _absolute_path(
            artifacts_root, is_directory=True, code="unsafe_artifact_path"
        )
        uri = _tracking_uri(database)
        artifact_uri = artifacts_root.as_uri()
        client = _load_client(uri, client_factory)
        try:
            experiment = client.get_experiment_by_name(EXPERIMENT_NAME)
            if experiment is None:
                experiment_id = client.create_experiment(
                    EXPERIMENT_NAME,
                    artifact_location=artifact_uri,
                )
                experiment = client.get_experiment(experiment_id)
            else:
                experiment_id = experiment.experiment_id
        except DeliveryError:
            raise
        except Exception:
            # A create reply may be lost after commit; refetch the fixed name.
            try:
                experiment = client.get_experiment_by_name(EXPERIMENT_NAME)
                if experiment is None:
                    raise DeliveryError("experiment_unavailable", correlation_id, attempt)
                experiment_id = experiment.experiment_id
            except DeliveryError:
                raise
            except Exception:
                raise DeliveryError("experiment_unavailable", correlation_id, attempt) from None
        if getattr(experiment, "artifact_location", None) != artifact_uri:
            raise DeliveryError(
                "experiment_artifact_location_conflict", correlation_id, attempt
            )

        digest = _canonical_digest(checked)
        tags = {
            "hyperreview_correlation_id": correlation_id,
            "hyperreview_attempt": str(attempt),
            "hyperreview_event_digest": digest,
        }
        tags.update({f"hyperreview.{key}": value for key, value in checked["metadata"].items()})
        tags.update(
            {f"hyperreview.metric.{key}": str(value) for key, value in checked["metrics"].items()}
        )
        run = _find_runs(client, experiment_id, correlation_id, attempt)
        if run is None:
            try:
                run = client.create_run(
                    experiment_id,
                    tags=tags,
                    run_name=f"HyperReview preview attempt {attempt}",
                )
            except Exception:
                # A create may have committed before the caller lost its reply.
                run = _find_runs(client, experiment_id, correlation_id, attempt)
                if run is None:
                    raise DeliveryError("run_create_unconfirmed", correlation_id, attempt) from None
        run = _ensure_run_tags(client, run, tags, correlation_id, attempt)
        run_id = _run_id(run)
        _ensure_metrics(client, run_id, checked["metrics"], correlation_id, attempt)

        trace = _find_traces(client, experiment_id, correlation_id, attempt)
        if trace is None:
            trace_id = _create_trace(client, checked, experiment_id, run_id, digest)
        else:
            trace_id = _verify_trace(
                client,
                trace,
                experiment_id,
                run_id,
                correlation_id,
                attempt,
                digest,
                checked["stages"],
            )

        try:
            run = client.get_run(run_id)
            status = getattr(getattr(run, "info", None), "status", None)
            status = getattr(status, "value", status)
            if status != "FINISHED":
                client.set_terminated(run_id, status="FINISHED")
            run = client.get_run(run_id)
        except DeliveryError:
            raise
        except Exception:
            raise DeliveryError("run_finalize_failed", correlation_id, attempt) from None
        if _run_id(run) != run_id or any(
            _run_tags(run).get(key) != value for key, value in tags.items()
        ):
            raise DeliveryError("run_readback_conflict", correlation_id, attempt)
        status = getattr(getattr(run, "info", None), "status", None)
        if getattr(status, "value", status) != "FINISHED":
            raise DeliveryError("run_not_confirmed", correlation_id, attempt)
        return _receipt(checked, experiment_id, run_id, trace_id, digest)
    except DeliveryError as error:
        if error.correlation_id is None:
            error.correlation_id = correlation_id
            error.attempt = attempt
        raise
    except Exception:
        # Never echo SDK exceptions, SQL text, tags, or event data to a caller.
        raise DeliveryError("tracking_delivery_failed", correlation_id, attempt) from None


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Deliver one sanitized HyperReview MLflow event")
    parser.add_argument("--database", required=True)
    parser.add_argument("--artifacts-root", required=True)
    args = parser.parse_args(argv)
    try:
        raw = sys.stdin.buffer.read(MAX_EVENT_BYTES + 1)
        if len(raw) > MAX_EVENT_BYTES:
            raise DeliveryError("event_too_large")
        event = json.loads(
            raw,
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("constant")),
        )
        result = deliver(event, args.database, args.artifacts_root)
        exit_code = 0
    except DeliveryError as error:
        result = error.as_receipt()
        exit_code = 1
    except Exception:
        result = DeliveryError("invalid_event").as_receipt()
        exit_code = 1
    try:
        output = _canonical_bytes(result)
    except Exception:
        output = (
            b'{"schema":"hyperreview.tracking-receipt.v1",'
            b'"tracking_status":"pending","failure_code":"receipt_invalid"}'
        )
        exit_code = 1
    if len(output) > MAX_RECEIPT_BYTES:
        output = (
            b'{"schema":"hyperreview.tracking-receipt.v1",'
            b'"tracking_status":"pending","failure_code":"receipt_too_large"}'
        )
        exit_code = 1
    sys.stdout.buffer.write(output + b"\n")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
