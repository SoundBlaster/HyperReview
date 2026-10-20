"""At-most-once private preview jobs under the intake worker's process lock."""

import hashlib
from itertools import islice
from pathlib import Path
import time
from uuid import UUID

from . import intake
from .storage import StorageError, read_json, write_bundle
from . import worker_generation


FILES = frozenset(("before.hc", "after.hc", "before.ir.json", "after.ir.json",
                   "diff.json", "result.json", "request.json", "compiler-receipt.json",
                   "preview.md", "preview-compact.md", "evidence.json",
                   "composition-plan.json", "generation-receipt.json", "metadata.json"))
MAX_FILE_BYTES = 2 * 1024 * 1024


def _setup(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS preview_jobs (
            job TEXT PRIMARY KEY, candidate TEXT NOT NULL, settings TEXT NOT NULL,
            state TEXT NOT NULL, updated_at INTEGER NOT NULL,
            generation_runs INTEGER NOT NULL DEFAULT 0, provider_attempts INTEGER,
            artifact TEXT, bundle_digest TEXT, failure_code TEXT
        );
        CREATE TABLE IF NOT EXISTS preview_events (
            job TEXT NOT NULL, state TEXT NOT NULL, at INTEGER NOT NULL, failure_code TEXT
        );
    """)


def _transition(db, job, state, now, code=None):
    with db:
        db.execute("UPDATE preview_jobs SET state=?,updated_at=?,failure_code=? WHERE job=?",
                   (state, now, code, job))
        db.execute("INSERT INTO preview_events VALUES (?,?,?,?)", (job, state, now, code))


def _manifest(directory):
    from . import worker
    worker._private_directory(directory)
    entries = list(islice(directory.iterdir(), len(FILES) + 1))
    worker._require({path.name for path in entries} == FILES,
                    "Private preview bundle has unexpected artifacts")
    hashes = {}
    for path in entries:
        worker._private_file(path)
        worker._require(path.stat().st_size <= MAX_FILE_BYTES)
        with path.open("rb") as source:
            raw = source.read(MAX_FILE_BYTES + 1)
        worker._require(len(raw) <= MAX_FILE_BYTES)
        hashes[path.name] = hashlib.sha256(raw).hexdigest()
    return intake.digest(hashes)


def _expire(db, root, now):
    from . import worker
    directory = worker._path(root / "previews")
    if directory.exists():
        worker._private_directory(directory)
        bundles = list(islice(directory.iterdir(), worker.MAX_RECEIPTS * 2 + 1))
        worker._require(len(bundles) <= worker.MAX_RECEIPTS * 2)
        for bundle in bundles:
            worker._require(str(UUID(bundle.name)) == bundle.name)
            worker._private_directory(bundle)
            if bundle.stat().st_mtime >= now - worker.RETENTION_SECONDS:
                continue
            entries = list(islice(bundle.iterdir(), len(FILES) + 1))
            worker._require(len(entries) <= len(FILES) and all(p.name in FILES for p in entries))
            for path in entries:
                worker._private_file(path)
            for path in entries:
                path.unlink()
            bundle.rmdir()
    for row in db.execute("SELECT job,artifact FROM preview_jobs WHERE artifact IS NOT NULL").fetchall():
        worker._require(str(UUID(row["artifact"])) == row["artifact"])
        if not worker._path(directory / row["artifact"]).exists():
            with db:
                db.execute("UPDATE preview_jobs SET artifact=NULL WHERE job=?", (row["job"],))


def _fresh(task, api):
    from . import worker
    account = api.get("user", "{login}")["login"]
    pr = intake.metadata(api, task["repository"], task["pr"])
    worker._require(type(pr) is dict)
    try:
        intake.eligible(task["repository"], task["pr"], pr, account)
    except intake.IntakeError:
        return False
    return (pr["base_sha"], pr["head_sha"]) == (task["base_sha"], task["head_sha"])


def _settings(options, gate_options=None):
    from . import worker
    try:
        fingerprint = worker_generation.fingerprint(options)
        return intake.digest([fingerprint, gate_options]) if gate_options is not None else fingerprint
    except worker_generation.PreviewJobError as error:
        raise worker.WorkerError("Private preview pipeline is unavailable") from error


def _finish_gate(db, root, config, task, job, outcome, observation_factory):
    if "review_gate" not in config or task["repository"] not in config["review_gate"]["repositories"]:
        return {}
    from .automatic_review_gate import GateError, complete
    from .worker import WorkerError
    try:
        complete(db, root, config, task, job, outcome, observation_factory)
        return {"review_gate_completion": "recorded"}
    except (GateError, WorkerError, intake.IntakeError, StorageError, OSError, ValueError, KeyError, TypeError):
        # Analysis receipts remain truthful if remote completion is interrupted.
        # A later due tick reconciles this independently of model execution.
        return {"review_gate_completion": "pending"}


def process_one(db, config, root, api, now, *, observation_factory=None, gate_factory=None):
    """Consume one retained intake handoff; never automatically replay a job key."""
    from . import worker
    observation_factory = observation_factory or (lambda: api)
    gate_factory = gate_factory or observation_factory
    _setup(db)
    _expire(db, root, now)
    gated = "review_gate" in config
    settings = _settings(config["preview"], config.get("review_gate"))
    for row in db.execute("SELECT j.job,j.state,j.settings,t.state task_state,t.artifact task_artifact FROM preview_jobs j"
                          " LEFT JOIN tasks t ON t.candidate=j.candidate").fetchall():
        if row["state"] == "analyzing":
            _transition(db, row["job"], "failed", now, "interrupted_no_replay")
        elif row["state"] == "queued" and row["task_artifact"] is None:
            _transition(db, row["job"], "failed", now, "handoff_unavailable")
        elif row["state"] != "stale" and (row["settings"] != settings
                                          or row["task_state"] != "request_prepared"):
            _transition(db, row["job"], "stale", now, "candidate_or_settings_changed")
    if gated:
        from .automatic_review_gate import GateError, reconcile
        try:
            reconcile(db, root, config, gate_factory)
        except GateError:
            return {"status": "review_gate_reconciliation_pending", "github_writes": None,
                    "generation_runs": 0, "provider_attempts": None}
    selected = None
    for task in db.execute("SELECT * FROM tasks WHERE state='request_prepared'"
                           " AND artifact IS NOT NULL ORDER BY updated_at,candidate"):
        identity = [task["candidate"], task["request_digest"], task["handoff_digest"], settings]
        job = intake.digest(identity)
        existing = db.execute("SELECT * FROM preview_jobs WHERE job=?", (job,)).fetchone()
        if existing is None or (existing["state"] == "queued" and existing["generation_runs"] == 0):
            selected = task
            break
    if selected is None:
        return None
    base = {"candidate": selected["candidate"], "job": job, "github_writes": None if gated else 0,
            "generation_runs": 0, "provider_attempts": None}
    if existing is None and db.execute("SELECT count(*) FROM preview_jobs").fetchone()[0] >= worker.MAX_RECEIPTS:
        return {**base, "status": "preview_capacity_reached"}
    if existing is None:
        with db:
            db.execute("INSERT INTO preview_jobs (job,candidate,settings,state,updated_at) VALUES (?,?,?,?,?)",
                       (job, selected["candidate"], settings, "queued", now))
            _transition(db, job, "queued", now)
    try:
        worker._require(worker._retained_handoff(root, selected), "Intake handoff is unavailable")
        if not _fresh(selected, observation_factory()):
            _transition(db, job, "stale", int(time.time()), "eligibility_or_revisions_changed")
            base.update(_finish_gate(db, root, config, selected, job, "stale", gate_factory))
            return {**base, "status": "preview_stale"}
        directory = root / "artifacts" / selected["artifact"]
        evidence = read_json(directory / "evidence.json")
        request = read_json(directory / "request.json")
        if gated and selected["repository"] in config["review_gate"]["repositories"]:
            from .automatic_review_gate import ensure
            base["review_gate_url"] = ensure(db, root, config, selected, job, gate_factory)
        # Persist before entering code which can contact the model. A crash or
        # ambiguous provider failure consumes this key instead of replaying it.
        with db:
            db.execute("UPDATE preview_jobs SET generation_runs=1 WHERE job=?", (job,))
            _transition(db, job, "analyzing", int(time.time()))
        base["generation_runs"] = 1
        completed = worker_generation.run(evidence, request, config["preview"])
        base["provider_attempts"] = completed["provider_attempts"]
        if not _fresh(selected, observation_factory()):
            _transition(db, job, "stale", int(time.time()), "eligibility_or_revisions_changed")
            base.update(_finish_gate(db, root, config, selected, job, "stale", gate_factory))
            return {**base, "status": "preview_stale"}
        artifacts = completed["artifacts"]
        worker._require(set(artifacts) == FILES)
        worker._require(all(type(value) is bytes and len(value) <= MAX_FILE_BYTES
                            for value in artifacts.values()))
        destination = write_bundle(artifacts, worker._private_directory(root / "previews", create=True))
        manifest = _manifest(destination)
        with db:
            db.execute("UPDATE preview_jobs SET artifact=?,bundle_digest=?,provider_attempts=? WHERE job=?",
                       (destination.name, manifest, completed["provider_attempts"], job))
            _transition(db, job, "preview_ready", int(time.time()))
        base.update(_finish_gate(db, root, config, selected, job, "success", gate_factory))
        return {**base, "status": "preview_ready", "bundle": str(destination),
                "preview": str(destination / "preview-compact.md"), "tracking_status": "not_started"}
    except worker_generation.PreviewJobError as error:
        code = error.code
    except (intake.IntakeError, worker.WorkerError, StorageError, OSError, ValueError, KeyError, TypeError):
        code = "preview_job_failed"
    except Exception as error:
        from .automatic_review_gate import GateError
        if not isinstance(error, GateError):
            raise
        code = error.code
    _transition(db, job, "failed", int(time.time()), code)
    base.update(_finish_gate(db, root, config, selected, job, "failed", gate_factory))
    return {**base, "status": "preview_failed", "failure_code": code}


def status(db, root, options, *, gate_options=None):
    from . import worker
    _setup(db)
    previews = []
    settings = _settings(options, gate_options)
    for row in db.execute("SELECT j.*,t.repository,t.pr,t.request_digest FROM preview_jobs j"
                          " JOIN tasks t ON t.candidate=j.candidate WHERE j.state='preview_ready'"
                          " AND t.state='request_prepared' AND j.artifact IS NOT NULL AND j.settings=?"
                          " ORDER BY j.updated_at DESC LIMIT 32", (settings,)):
        worker._require(str(UUID(row["artifact"])) == row["artifact"])
        directory = worker._path(root / "previews" / row["artifact"])
        if not directory.exists():
            continue
        worker._require(_manifest(directory) == row["bundle_digest"], "Private preview bundle changed")
        previews.append({"job": row["job"], "candidate": row["candidate"],
                         "repository": row["repository"], "pr": row["pr"],
                         "request_digest": row["request_digest"], "bundle": str(directory),
                         "preview": str(directory / "preview-compact.md"),
                         "tracking_status": "not_started", "last_rechecked_at": row["updated_at"]})
    return {"previews": previews,
            "preview_counts": {row["state"]: row["n"] for row in
                               db.execute("SELECT state,count(*) n FROM preview_jobs GROUP BY state")}}
