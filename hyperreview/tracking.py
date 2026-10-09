"""Metadata-only tracking events and a bounded local delivery outbox."""

import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import threading
from uuid import UUID

from . import intake, model_contract
from .storage import read_json


EVENT_SCHEMA = "hyperreview.tracking-event.v1"
MAX_EVENT_BYTES = 65536
MAX_PENDING_EVENTS = 100
STAGES = ("collection", "inference", "projection_validation", "rendering")
METRICS = {"included_source_records", "omissions", "source_bytes", "request_bytes",
           "result_bytes", "change_count", "before_nodes", "after_nodes",
           "inference_elapsed_ms", "validation_elapsed_ms", "input_tokens", "output_tokens"}
METADATA = {"repository", "pr", "merge_base_sha", "head_sha", "evidence_digest",
            "request_digest", "result_digest", "abstraction_profile", "prompt_version",
            "provider", "model_identity_sha256", "compiler_sha256", "compiler_resolver_name",
            "compiler_resolver_version", "delivery_mode"}
_LEGACY_PROMPT_VERSIONS = frozenset(("composition-v7",))
_UUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_HEX40 = re.compile(r"[0-9a-f]{40}\Z")


class TrackingError(Exception):
    pass


def _require(condition, message):
    if not condition:
        raise TrackingError(message)


def validate_event(event):
    """Allow only application-owned scalar metadata; never accept arbitrary logs."""
    _require(type(event) is dict and set(event) == {
        "schema", "correlation_id", "attempt", "metadata", "metrics", "stages"},
        "Tracking event fields are invalid")
    _require(event["schema"] == EVENT_SCHEMA, "Tracking event schema is unsupported")
    correlation = event["correlation_id"]
    _require(type(correlation) is str and _UUID.fullmatch(correlation) is not None,
             "Tracking correlation ID is invalid")
    _require(str(UUID(correlation)) == correlation, "Tracking correlation ID is not canonical")
    _require(type(event["attempt"]) is int and event["attempt"] == 1,
             "Manual tracking supports exactly one recorded attempt")
    metadata = event["metadata"]
    _require(type(metadata) is dict and set(metadata) == METADATA
             and all(type(value) is str and 1 <= len(value) <= 128 for value in metadata.values()),
             "Tracking metadata fields are invalid")
    for field in ("evidence_digest", "request_digest", "result_digest",
                  "model_identity_sha256", "compiler_sha256"):
        _require(_HEX64.fullmatch(metadata[field]) is not None, "Tracking digest is invalid")
    for field in ("merge_base_sha", "head_sha"):
        _require(_HEX40.fullmatch(metadata[field]) is not None, "Tracking revision is invalid")
    _require(metadata["repository"] in intake.ALLOWLIST
             and re.fullmatch(r"[1-9][0-9]{0,9}", metadata["pr"]) is not None,
             "Tracking repository or PR is invalid")
    _require(metadata["abstraction_profile"] == model_contract.ABSTRACTION_PROFILE
             and metadata["prompt_version"] in (_LEGACY_PROMPT_VERSIONS | {model_contract.PROMPT_VERSION})
             and metadata["provider"] in ("codex", "lmstudio", "ollama")
             and metadata["delivery_mode"] == "preview"
             and metadata["compiler_resolver_name"] == "hypercode-swift"
             and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[a-z0-9.-]+)?",
                              metadata["compiler_resolver_version"]) is not None,
             "Tracking profile metadata is invalid")
    metrics = event["metrics"]
    _require(type(metrics) is dict and set(metrics) <= METRICS
             and all(type(value) is int and 0 <= value <= 10**12 for value in metrics.values()),
             "Tracking metrics are invalid")
    stages = event["stages"]
    _require(type(stages) is list and len(stages) == len(STAGES), "Tracking stages are invalid")
    for stage, name in zip(stages, STAGES):
        _require(type(stage) is dict and set(stage) == {"name", "status", "elapsed_ms"}
                 and stage["name"] == name and stage["status"] in ("completed", "unavailable")
                 and (stage["elapsed_ms"] is None or (type(stage["elapsed_ms"]) is int
                      and 0 <= stage["elapsed_ms"] <= 10**12))
                 and (stage["status"] != "unavailable" or stage["elapsed_ms"] is None),
                 "Tracking stage is invalid")
    try:
        _require(len(intake.encoded(event)) <= MAX_EVENT_BYTES, "Tracking event exceeds its byte limit")
    except (ValueError, TypeError, RecursionError, OverflowError) as error:
        raise TrackingError("Tracking event is not canonical JSON") from error
    return event


def _read_artifact(bundle, name, limit=MAX_EVENT_BYTES):
    path = bundle / name
    _require(not path.is_symlink() and path.is_file(), "Preview artifact is missing or is a symlink")
    try:
        return read_json(path, max_bytes=limit)
    except (OSError, ValueError) as error:
        raise TrackingError("Preview artifact cannot be read") from error


def _ir_node_count(raw):
    try:
        document = json.loads(raw)
    except (ValueError, UnicodeError) as error:
        raise TrackingError("Compiled IR cannot be read") from error
    _require(type(document) is dict and type(document.get("nodes")) is list,
             "Compiled IR nodes are invalid")
    stack = list(document["nodes"])
    count = 0
    while stack:
        node = stack.pop()
        count += 1
        _require(count <= 10000 and type(node) is dict and type(node.get("children")) is list,
                 "Compiled IR node count is invalid")
        stack.extend(node["children"])
    return count


def _safe_directory(path, *, create=False):
    path = Path(path)
    _require(path.is_absolute(), "Tracking directory must be absolute")
    for parent in (*reversed(path.parents), path):
        _require(not parent.is_symlink(), "Tracking paths must not traverse symlinks")
    if create:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    _require(path.is_dir(), "Tracking directory does not exist")
    return path


def build_event(bundle):
    """Recheck private bundle bindings and export a fixed metadata allowlist."""
    bundle = _safe_directory(bundle)
    request = _read_artifact(bundle, "request.json", 262144)
    result = _read_artifact(bundle, "result.json", 1024 * 1024)
    metadata = _read_artifact(bundle, "metadata.json")
    compiler = _read_artifact(bundle, "compiler-receipt.json")
    generation = _read_artifact(bundle, "generation-receipt.json")
    evidence = _read_artifact(bundle, "evidence.json", 262144)
    model_contract.validate_request(request)
    model_contract.validate_result(result, request)
    selection = request["source_selection"]
    _require(model_contract.prepare_request(evidence, max_source_bytes=selection["max_source_bytes"],
                                           include_paths=selection["include_paths"]) == request,
             "Tracking evidence no longer matches the selected request")
    preview_path = bundle / "preview.md"
    _require(not preview_path.is_symlink() and preview_path.is_file()
             and preview_path.stat().st_size <= 2 * 1024 * 1024,
             "Tracking requires a bounded local preview artifact")
    for side in ("before", "after"):
        path = bundle / (side + ".hc")
        _require(not path.is_symlink() and path.is_file()
                 and path.stat().st_size <= 262144
                 and path.read_bytes() == result[side + "_hc"].encode("utf-8"),
                 "Projection artifact does not match its bound result")
    result_digest = intake.digest(result)
    for receipt in (metadata, compiler, generation):
        _require(receipt.get("request_digest") == request["request_digest"]
                 and receipt.get("result_digest") == result_digest,
                 "Tracking bundle receipts do not bind the analysis")
    _require(generation.get("reviewer_profile_version") == request["reviewer_profile"]["version"]
             and generation.get("reviewer_profile_sha256") == request["reviewer_profile"]["sha256"],
             "Generation receipt reviewer profile does not match the request")
    _require(metadata.get("schema") == "hyperreview.preview.v1"
             and metadata.get("stage") in ("projections_validated", "ready")
             and compiler.get("stage") == "projections_validated"
             and generation.get("stage") == "model_generated"
             and metadata.get("delivery_mode") == "preview" and metadata.get("attempt") == 1,
             "Tracking requires a compiled preview bundle")
    ir_node_counts = {}
    for artifact, field in (("before.ir.json", "before_ir_sha256"),
                            ("after.ir.json", "after_ir_sha256"), ("diff.json", "diff_sha256")):
        path = bundle / artifact
        _require(not path.is_symlink() and path.is_file(), "Compiled artifact is unavailable")
        with path.open("rb") as stream:
            raw = stream.read(1024 * 1024 + 1)
        _require(len(raw) <= 1024 * 1024
                 and hashlib.sha256(raw).hexdigest() == compiler.get(field),
                 "Compiled artifact fingerprint mismatch")
        if artifact.endswith(".ir.json"):
            ir_node_counts[artifact.split(".", 1)[0]] = _ir_node_count(raw)
    resolver = compiler["after_resolver"]
    _require(compiler["before_resolver"] == resolver, "Compiler resolver identity changed between sides")
    model_identity = generation["model"].encode("utf-8")
    if generation["provider"] == "codex":
        _require(generation.get("reasoning_effort") in ("low", "medium", "high"),
                 "Codex tracking requires a recorded reasoning effort")
        model_identity = intake.encoded({"model": generation["model"],
                                         "reasoning_effort": generation["reasoning_effort"]})
    values = {
        "repository": request["repository"], "pr": str(request["pr"]),
        "merge_base_sha": request["merge_base_sha"], "head_sha": request["head_sha"],
        "evidence_digest": request["evidence_digest"], "request_digest": request["request_digest"],
        "result_digest": result_digest, "abstraction_profile": request["abstraction_profile"],
        "prompt_version": request["prompt_version"],
        "provider": generation["provider"],
        "model_identity_sha256": hashlib.sha256(model_identity).hexdigest(),
        "compiler_sha256": compiler["compiler_sha256"],
        "compiler_resolver_name": resolver["name"], "compiler_resolver_version": resolver["version"],
        "delivery_mode": "preview",
    }
    metrics = {
        "included_source_records": len(request["sources"]), "omissions": len(request["omissions"]),
        "source_bytes": request["source_selection"]["included_source_bytes"],
        "request_bytes": len(intake.encoded(request)), "result_bytes": len(intake.encoded(result)),
        "change_count": compiler["change_count"], "before_nodes": ir_node_counts["before"],
        "after_nodes": ir_node_counts["after"],
    }
    for source, field, target in ((generation, "elapsed_ms", "inference_elapsed_ms"),
                                (compiler, "elapsed_ms", "validation_elapsed_ms"),
                                (generation, "input_tokens", "input_tokens"),
                                (generation, "output_tokens", "output_tokens")):
        if source.get(field) is not None:
            metrics[target] = source[field]
    event = {
        "schema": EVENT_SCHEMA, "correlation_id": metadata["tracking_correlation_id"],
        "attempt": metadata["attempt"], "metadata": values, "metrics": metrics,
        "stages": [
            {"name": "collection", "status": "completed", "elapsed_ms": None},
            {"name": "inference", "status": "completed", "elapsed_ms": metrics.get("inference_elapsed_ms")},
            {"name": "projection_validation", "status": "completed", "elapsed_ms": metrics.get("validation_elapsed_ms")},
            {"name": "rendering", "status": "completed", "elapsed_ms": None},
        ],
    }
    return validate_event(event)


def _atomic_json(path, value):
    raw = intake.encoded(value)
    _require(len(raw) <= MAX_EVENT_BYTES, "Operational tracking data exceeds its byte limit")
    _atomic_bytes(path, raw)


def _atomic_bytes(path, raw):
    _require(not path.is_symlink(), "Tracking output must not be a symlink")
    descriptor, temporary = tempfile.mkstemp(prefix=".tracking-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        folder = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(folder)
        finally:
            os.close(folder)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _remove_pending_event(root, event_path):
    """Durably remove an outbox item after its receipt has been validated."""
    _require(event_path.parent == root, "Tracking event path escaped its spool")
    event_path.unlink(missing_ok=True)
    descriptor = os.open(root, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _validate_receipt(receipt, event):
    _require(type(receipt) is dict and set(receipt) == {
        "schema", "correlation_id", "attempt", "tracking_status", "experiment_id",
        "run_id", "trace_id", "event_digest"}, "Tracking receipt fields are invalid")
    _require(receipt["schema"] == "hyperreview.tracking-receipt.v1"
             and receipt["tracking_status"] == "confirmed"
             and receipt["correlation_id"] == event["correlation_id"]
             and receipt["attempt"] == event["attempt"]
             and receipt["event_digest"] == intake.digest(event), "Tracking receipt binding is invalid")
    for key in ("experiment_id", "run_id", "trace_id"):
        _require(type(receipt[key]) is str
                 and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", receipt[key]) is not None,
                 "Tracking server identity is invalid")
    return receipt


def _run_delivery(event, runtime_python, database, artifacts_root, timeout_seconds):
    """The child receives only the sanitized event, never a source-bearing bundle."""
    runtime_python = Path(runtime_python)
    database, artifacts_root = Path(database), Path(artifacts_root)
    _require(runtime_python.is_absolute() and runtime_python.is_file()
             and os.access(runtime_python, os.X_OK), "Tracking runtime Python is unavailable")
    _require(database.is_absolute() and not database.is_symlink(), "Tracking database path is invalid")
    _safe_directory(database.parent, create=True)
    _safe_directory(artifacts_root, create=True)
    _require(type(timeout_seconds) is int and 1 <= timeout_seconds <= 300,
             "Tracking timeout must be an integer from 1 through 300")
    env = {
        "PATH": os.defpath, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
        "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
        "MLFLOW_TRACKING_URI": "sqlite:///" + str(database),
        "MLFLOW_DISABLE_AGENT_HINT": "1", "MLFLOW_ENABLE_ASYNC_TRACE_LOGGING": "false",
        "MLFLOW_ENABLE_ASYNC_LOGGING": "false", "MLFLOW_ALLOW_HTTP_REDIRECTS": "false",
    }
    with tempfile.TemporaryFile() as source:
        source.write(intake.encoded(event))
        source.seek(0)
        proc = subprocess.Popen([str(runtime_python), "-m", "hyperreview.mlflow_delivery",
                                 "--database", str(database), "--artifacts-root", str(artifacts_root)],
                                stdin=source, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                env=env, cwd=database.parent, start_new_session=True)
        buffers = {"stdout": bytearray(), "stderr": bytearray()}
        total = [0]
        lock = threading.Lock()
        overflow = threading.Event()

        def kill():
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

        def drain(name, stream):
            try:
                while True:
                    chunk = stream.read1(8192)
                    if not chunk:
                        return
                    with lock:
                        remaining = MAX_EVENT_BYTES - total[0]
                        buffers[name].extend(chunk[:max(0, remaining)])
                        total[0] += min(max(0, remaining), len(chunk))
                        if len(chunk) > remaining:
                            overflow.set()
                    if overflow.is_set():
                        kill()
            except OSError:
                overflow.set()
                kill()

        readers = [threading.Thread(target=drain, args=(name, stream), daemon=True)
                   for name, stream in (("stdout", proc.stdout), ("stderr", proc.stderr))]
        for reader in readers:
            reader.start()
        try:
            try:
                code = proc.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired as error:
                kill()
                proc.wait()
                raise TrackingError("Tracking delivery timed out; event remains pending") from error
            for reader in readers:
                reader.join(timeout=0.5)
            _require(not overflow.is_set() and not any(reader.is_alive() for reader in readers),
                     "Tracking delivery output exceeded bounds; event remains pending")
            _require(code == 0, "Tracking delivery failed; event remains pending")
            try:
                receipt = json.loads(buffers["stdout"])
            except (ValueError, UnicodeError) as error:
                raise TrackingError("Tracking delivery returned invalid data") from error
            return _validate_receipt(receipt, event)
        finally:
            kill()
            proc.wait()
            for reader in readers:
                reader.join(timeout=0.5)
            for stream in (proc.stdout, proc.stderr):
                if not any(reader.is_alive() for reader in readers):
                    stream.close()


def reconcile(event, *, spool_root, runtime_python, database, artifacts_root,
              timeout_seconds=120, delivery=None):
    """Serialize replay, persist events first, and keep durable receipts separately."""
    validate_event(event)
    root = _safe_directory(spool_root, create=True)
    lock_path = root / ".delivery.lock"
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise TrackingError("Another tracking reconciliation owns the local lock") from error
        database, artifacts_root = Path(database), Path(artifacts_root)
        _require(database.is_absolute() and not database.is_symlink(), "Tracking database path is invalid")
        _safe_directory(database.parent, create=True)
        _safe_directory(artifacts_root, create=True)
        destination = {"database_sha256": hashlib.sha256(str(database).encode()).hexdigest(),
                       "artifacts_root_sha256": hashlib.sha256(str(artifacts_root).encode()).hexdigest(),
                       "mlflow_version": "3.16.1"}
        destination_path = root / ".destination.json"
        _require(not destination_path.is_symlink(), "Tracking destination receipt must not be a symlink")
        if destination_path.exists():
            _require(read_json(destination_path, MAX_EVENT_BYTES) == destination,
                     "Tracking spool is already bound to another destination")
        else:
            _atomic_json(destination_path, destination)
        event_path = root / (event["correlation_id"] + ".json")
        receipt_path = root / (event["correlation_id"] + ".receipt.json")
        _require(not event_path.is_symlink() and not receipt_path.is_symlink(),
                 "Tracking outbox files must not be symlinks")
        if receipt_path.exists():
            receipt = _validate_receipt(read_json(receipt_path, MAX_EVENT_BYTES), event)
            _remove_pending_event(root, event_path)
            return receipt
        if event_path.exists():
            _require(read_json(event_path, MAX_EVENT_BYTES) == event, "Tracking event identity conflict")
        else:
            count = sum(bool(_UUID.fullmatch(path.stem)) for path in root.glob("*.json"))
            _require(count < MAX_PENDING_EVENTS, "Tracking spool is full; stop new analyses")
            _atomic_json(event_path, event)
        method = delivery or _run_delivery
        receipt = method(event, runtime_python, database, artifacts_root, timeout_seconds)
        _validate_receipt(receipt, event)
        _atomic_json(receipt_path, receipt)
        _remove_pending_event(root, event_path)
        return receipt
    finally:
        os.close(descriptor)


def pending_events(spool_root):
    root = _safe_directory(spool_root, create=True)
    for path in sorted(root.glob("*.json")):
        if _UUID.fullmatch(path.stem):
            _require(not path.is_symlink(), "Tracking event must not be a symlink")
            yield validate_event(read_json(path, MAX_EVENT_BYTES))


def update_bundle_tracking(bundle, receipt=None):
    """The durable outbox receipt stays independent of the source-bearing bundle."""
    bundle = _safe_directory(bundle)
    event = build_event(bundle)
    metadata = _read_artifact(bundle, "metadata.json")
    if receipt is None:
        metadata["tracking_status"] = "tracking_pending"
    else:
        _validate_receipt(receipt, event)
        _atomic_json(bundle / "tracking-receipt.json", receipt)
        metadata.update({"tracking_status": "confirmed", "stage": "ready",
                         "experiment_id": receipt["experiment_id"], "run_id": receipt["run_id"],
                         "trace_id": receipt["trace_id"]})
    _atomic_json(bundle / "metadata.json", metadata)
    return event
