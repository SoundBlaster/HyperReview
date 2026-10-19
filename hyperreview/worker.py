"""Serialized intake and explicitly configured private preview scheduling."""

from contextlib import contextmanager
import fcntl
import hashlib
from itertools import islice
import os
from pathlib import Path
import sqlite3
import stat
import time
from uuid import UUID

from . import intake, model_contract, reviewer_profile
from .storage import StorageError, read_json, write_bundle
from .worker_task_eligibility import WorkerTaskContext, WorkerTaskEligibility


CONFIG_SCHEMA = "hyperreview.worker-config.v1"
PREVIEW_CONFIG_SCHEMA = "hyperreview.worker-config.v2"
TASK_SCHEMA = "hyperreview.intake-task.v1"
PAGE_SIZE = 30
MAX_PENDING = 32
MAX_RECEIPTS = 2048
RETENTION_SECONDS = 7 * 86400
_ARTIFACT_FILES = frozenset(("evidence.json", "request.json", "metadata.json"))
_LOG_FILES = ("worker.stdout.log", "worker.stderr.log")
_STATES = frozenset(("queued", "collecting", "request_prepared", "failed", "stale"))


class WorkerError(Exception):
    """Sanitized worker configuration or state failure."""


def _require(condition, message="Worker input or state is invalid"):
    if not condition:
        raise WorkerError(message)


def _path(path):
    path = Path(path)
    _require(path.is_absolute() and ".." not in path.parts)
    for parent in (*reversed(path.parents), path):
        _require(not parent.is_symlink(), "Worker paths must not traverse symlinks")
    return path


def _private_directory(path, *, create=False):
    path = _path(path)
    if create:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = path.stat()
    _require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
             and stat.S_IMODE(info.st_mode) & 0o077 == 0,
             "Worker directory must be owner-private")
    return path


def _private_file(path):
    path = _path(path)
    info = path.stat()
    _require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
             and stat.S_IMODE(info.st_mode) & 0o077 == 0,
             "Worker file must be owner-private")
    return path


def _prepare_logs(root):
    """Create private files before launchd opens its stdout/stderr targets."""
    log_root = _private_directory(Path(root) / "logs", create=True)
    for name in _LOG_FILES:
        path = _path(log_root / name)
        if not path.exists():
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                                 | getattr(os, "O_NOFOLLOW", 0), 0o600)
            os.close(descriptor)
        _private_file(path)
        # Owner-private can still be 0400/000; creation is also affected by the
        # caller's umask. launchd needs writable targets, not just private ones.
        os.chmod(path, 0o600, follow_symlinks=False)
    return log_root


def load_config(path):
    path = _private_file(path)
    _private_directory(path.parent)
    config = read_json(path, max_bytes=16384)
    _require(type(config) is dict)
    base_keys = {"schema", "repositories", "interval_seconds", "state_root"}
    if config.get("schema") == CONFIG_SCHEMA:
        _require(set(config) == base_keys)
    elif config.get("schema") == PREVIEW_CONFIG_SCHEMA:
        _require(set(config) == base_keys | {"preview"})
        from .worker_generation import PreviewJobError, validate_options
        try:
            validate_options(config["preview"])
        except PreviewJobError as error:
            raise WorkerError("Private preview configuration is invalid") from error
    else:
        raise WorkerError("Worker configuration schema is invalid")
    repositories = config["repositories"]
    _require(type(repositories) is list and 1 <= len(repositories) <= len(intake.ALLOWLIST))
    _require(all(type(repo) is str and repo in intake.ALLOWLIST for repo in repositories))
    _require(len(repositories) == len(set(repositories)))
    interval = config["interval_seconds"]
    _require(type(interval) is int and 300 <= interval <= 86400)
    _require(type(config["state_root"]) is str)
    _path(config["state_root"])
    return config


def create_config(*, repositories, state_root, output_root, interval_seconds=300, preview=None):
    config = {"schema": CONFIG_SCHEMA, "repositories": list(repositories),
              "interval_seconds": interval_seconds, "state_root": str(state_root)}
    if preview is not None:
        from .worker_generation import PreviewJobError, validate_options
        try:
            validate_options(preview)
        except PreviewJobError as error:
            raise WorkerError("Private preview configuration is invalid") from error
        config.update(schema=PREVIEW_CONFIG_SCHEMA, preview=preview)
    # Validate before creating any state directory; reuse the file boundary below.
    _require(1 <= len(config["repositories"]) <= len(intake.ALLOWLIST))
    _require(all(type(repo) is str and repo in intake.ALLOWLIST for repo in repositories))
    _require(len(config["repositories"]) == len(set(config["repositories"])))
    _require(type(interval_seconds) is int and 300 <= interval_seconds <= 86400)
    _private_directory(state_root, create=True)
    _prepare_logs(state_root)
    _private_directory(output_root, create=True)
    destination = write_bundle({"config.json": intake.encoded(config)}, output_root)
    load_config(destination / "config.json")
    return destination


@contextmanager
def _state(root):
    root = _private_directory(root, create=True)
    lock = _path(root / "worker.lock")
    descriptor = os.open(lock, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    db = None
    try:
        _private_file(lock)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield None
            return
        path = _path(root / "journal.sqlite3")
        if not path.exists():
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)
        _private_file(path)
        # The lock covers discovery, state changes, collection and retention.
        db = sqlite3.connect(path, timeout=0)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=DELETE")
        db.execute("PRAGMA synchronous=FULL")
        db.executescript("""
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS tasks (
                candidate TEXT PRIMARY KEY, repository TEXT NOT NULL, pr INTEGER NOT NULL,
                base_sha TEXT NOT NULL, head_sha TEXT NOT NULL, pipeline TEXT NOT NULL,
                state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                retry_after INTEGER NOT NULL DEFAULT 0, updated_at INTEGER NOT NULL,
                artifact TEXT, evidence_digest TEXT, request_digest TEXT, handoff_digest TEXT,
                failure_code TEXT
            );
            CREATE TABLE IF NOT EXISTS events (
                candidate TEXT NOT NULL, state TEXT NOT NULL, at INTEGER NOT NULL,
                attempt INTEGER NOT NULL, failure_code TEXT
            );
        """)
        yield db
    finally:
        if db is not None:
            db.close()
        os.close(descriptor)


def _transition(db, candidate, state, now, failure_code=None):
    _require(state in _STATES)
    with db:
        db.execute("UPDATE tasks SET state=?,updated_at=?,failure_code=? WHERE candidate=?",
                   (state, now, failure_code, candidate))
        row = db.execute("SELECT attempts FROM tasks WHERE candidate=?", (candidate,)).fetchone()
        db.execute("INSERT INTO events VALUES (?,?,?,?,?)",
                   (candidate, state, now, row["attempts"], failure_code))


def _pipeline():
    code = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
            for name in ("worker.py", "worker_task_eligibility.py", "intake.py",
                         "model_contract.py", "pr_eligibility.py")}
    return intake.digest({"task_schema": TASK_SCHEMA, "code": code,
                          "intake_policy": intake.POLICY,
                          "request_schema": model_contract.REQUEST_SCHEMA,
                          "prompt": model_contract.PROMPT_VERSION,
                          "profile": reviewer_profile.identity(),
                          "abstraction": model_contract.ABSTRACTION_PROFILE,
                          "provider": "not_invoked", "delivery": "request_only"})


def _meta(db, key, default=0):
    row = db.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def _set_meta(db, key, value):
    with db:
        db.execute("INSERT OR REPLACE INTO metadata VALUES (?,?)", (key, value))


def _retained_handoff(root, task):
    artifact = task["artifact"]
    if artifact is None:
        return False
    _require(str(UUID(artifact)) == artifact)
    directory = _path(root / "artifacts" / artifact)
    if not directory.exists():
        return False
    _private_directory(directory)
    for name in _ARTIFACT_FILES:
        _private_file(directory / name)
    evidence = read_json(directory / "evidence.json")
    request = read_json(directory / "request.json")
    handoff = read_json(directory / "metadata.json", max_bytes=16384)
    _require(model_contract.prepare_request(evidence) == request
             and intake.digest(handoff) == task["handoff_digest"]
             and request["request_digest"] == task["request_digest"]
             and evidence["evidence_digest"] == task["evidence_digest"]
             and handoff["candidate"] == task["candidate"])
    return True


def _supersede(db, repo, number, candidate, now):
    for previous in db.execute("SELECT candidate FROM tasks WHERE repository=? AND pr=?"
                               " AND candidate!=? AND state!='stale'",
                               (repo, number, candidate)).fetchall():
        _transition(db, previous[0], "stale", now, "superseded")


def _discover(db, config, api, pipeline, now):
    account = api.get("user", "{login}")["login"]
    _require(account == intake.AUTHOR, "Worker GitHub account differs from configured author")
    discovered = 0
    queue_full = False
    for repo in config["repositories"]:
        page = _meta(db, "page:" + repo, 1)
        _require(type(page) is int and 1 <= page <= 10000)
        records = api.get(f"repos/{repo}/pulls?state=open&sort=created&direction=asc"
                          f"&per_page={PAGE_SIZE}&page={page}",
                          "[.[]|{number,state,draft,author:.user.login,base_repo:.base.repo.full_name,"
                          "head_repo:.head.repo.full_name,base_sha:.base.sha,head_sha:.head.sha}]")
        _require(type(records) is list and len(records) <= PAGE_SIZE)
        for pr in records:
            _require(type(pr) is dict)
            number = pr.get("number")
            if type(number) is not int or number <= 0:
                raise WorkerError("Worker received an invalid PR identity")
            try:
                intake.eligible(repo, number, pr, account)
            except intake.IntakeError:
                continue
            candidate = intake.digest([repo, number, pr["base_sha"], pr["head_sha"], pipeline])
            existing = db.execute("SELECT * FROM tasks WHERE candidate=?", (candidate,)).fetchone()
            if existing is not None and existing["state"] != "stale":
                continue
            if existing is not None and _retained_handoff(Path(config["state_root"]), existing):
                _supersede(db, repo, number, candidate, now)
                _transition(db, candidate, "request_prepared", now)
                discovered += 1
                continue
            if existing is not None and existing["attempts"] >= 2:
                _transition(db, candidate, "failed", now, "attempts_exhausted")
                continue
            pending = db.execute("SELECT count(*) FROM tasks WHERE state IN ('queued','collecting')"
                                 " OR (state='failed' AND attempts<2)").fetchone()[0]
            total = db.execute("SELECT count(*) FROM tasks").fetchone()[0]
            if pending >= MAX_PENDING or (existing is None and total >= MAX_RECEIPTS):
                queue_full = True
                break
            _supersede(db, repo, number, candidate, now)
            with db:
                if existing is None:
                    db.execute("INSERT INTO tasks (candidate,repository,pr,base_sha,head_sha,pipeline,"
                               "state,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                               (candidate, repo, number, pr["base_sha"], pr["head_sha"],
                                pipeline, "queued", now))
                else:
                    db.execute("UPDATE tasks SET retry_after=0,artifact=NULL WHERE candidate=?",
                               (candidate,))
                _transition(db, candidate, "queued", now)
            discovered += 1
        if queue_full:
            break  # Retry this page; do not lose candidates beyond the capacity bound.
        _set_meta(db, "page:" + repo, page + 1 if len(records) == PAGE_SIZE else 1)
    return discovered, queue_full


def _expire_artifacts(db, root, now):
    artifact_root = _path(root / "artifacts")
    if not artifact_root.exists():
        with db:
            db.execute("UPDATE tasks SET artifact=NULL WHERE artifact IS NOT NULL")
        return
    _private_directory(artifact_root)
    directories = list(islice(artifact_root.iterdir(), MAX_RECEIPTS * 2 + 1))
    _require(len(directories) <= MAX_RECEIPTS * 2, "Worker artifact inventory exceeds its bound")
    # Include orphan bundles left by a crash between the bundle and journal writes.
    for directory in directories:
        _require(str(UUID(directory.name)) == directory.name)
        _private_directory(directory)
        if directory.stat().st_mtime >= now - RETENTION_SECONDS:
            continue
        entries = list(islice(directory.iterdir(), len(_ARTIFACT_FILES) + 1))
        _require(len(entries) <= len(_ARTIFACT_FILES)
                 and all(item.name in _ARTIFACT_FILES for item in entries))
        for item in entries:
            _private_file(item)
        for item in entries:
            item.unlink()
        directory.rmdir()
        with db:
            db.execute("UPDATE tasks SET artifact=NULL WHERE artifact=?", (directory.name,))
    # Recover a crash after deletion but before the journal reference was cleared.
    for row in db.execute("SELECT candidate,artifact FROM tasks WHERE artifact IS NOT NULL").fetchall():
        _require(str(UUID(row["artifact"])) == row["artifact"])
        if not _path(artifact_root / row["artifact"]).exists():
            with db:
                db.execute("UPDATE tasks SET artifact=NULL WHERE candidate=?", (row["candidate"],))


def _rotate_logs(root):
    log_root = _prepare_logs(root)
    for name in _LOG_FILES:
        path = _path(log_root / name)
        if not path.exists():
            continue
        _private_file(path)
        if path.stat().st_size < 65536:
            continue
        previous = _path(log_root / (name + ".previous"))
        if previous.exists():
            _private_file(previous)
            previous.unlink()
        os.replace(path, previous)
        # launchd opens log targets before applying the child's Umask. Leave a
        # private current target for the next launch instead of a missing path.
        _prepare_logs(root)


def tick(config_path, *, api=None):
    """Perform at most one intake or explicitly configured private-preview job."""
    config = load_config(config_path)
    root = _private_directory(config["state_root"], create=True)
    now = int(time.time())
    with _state(root) as db:
        if db is None:
            return {"status": "busy", "github_writes": 0, "model_calls": 0}
        _rotate_logs(root)
        if now < _meta(db, "next_poll"):
            return {"status": "not_due", "github_writes": 0, "model_calls": 0}
        _set_meta(db, "next_poll", now + config["interval_seconds"])
        _expire_artifacts(db, root, now)
        for row in db.execute("SELECT candidate FROM tasks WHERE state='collecting'").fetchall():
            _transition(db, row[0], "failed", now, "interrupted")
        pipeline = _pipeline()
        for row in db.execute("SELECT candidate,repository,pipeline FROM tasks"
                              " WHERE state!='stale'").fetchall():
            if row["repository"] not in config["repositories"] or row["pipeline"] != pipeline:
                _transition(db, row["candidate"], "stale", now, "policy_changed")
        api = api or intake.GitHub()
        discovered, full = _discover(db, config, api, pipeline, now)
        if "preview" in config:
            from .worker_preview import process_one
            completed_preview = process_one(db, config, root, api, now)
            if completed_preview is not None:
                return {"discovered": discovered, "queue_full": full, **completed_preview}
        policy = WorkerTaskEligibility()
        selected = next((row for row in db.execute("SELECT * FROM tasks ORDER BY updated_at,candidate")
                         if policy.is_satisfied_by(WorkerTaskContext(
                             row["state"], row["attempts"], row["retry_after"], now))), None)
        result = {"status": "idle", "discovered": discovered, "queue_full": full,
                  "github_writes": 0, "model_calls": 0}
        if selected is None:
            return result
        candidate = selected["candidate"]
        with db:
            db.execute("UPDATE tasks SET attempts=attempts+1 WHERE candidate=?", (candidate,))
            _transition(db, candidate, "collecting", now)
        try:
            pack = intake.collect(selected["repository"], selected["pr"], api=api)
            if (pack["base_sha"], pack["head_sha"]) != (selected["base_sha"], selected["head_sha"]):
                _transition(db, candidate, "stale", int(time.time()), "revisions_changed")
                return {**result, "status": "stale", "candidate": candidate}
            request = model_contract.prepare_request(pack)
            handoff = {"schema": TASK_SCHEMA, "candidate": candidate,
                       "stage": "request_prepared", "delivery_mode": "request_only",
                       "repository": selected["repository"], "pr": selected["pr"],
                       "base_sha": pack["base_sha"], "merge_base_sha": pack["merge_base_sha"],
                       "head_sha": pack["head_sha"], "pipeline": pipeline,
                       "evidence_digest": pack["evidence_digest"],
                       "request_digest": request["request_digest"],
                       "model_calls": 0, "github_writes": 0}
            artifact_root = _private_directory(root / "artifacts", create=True)
            destination = write_bundle({"evidence.json": intake.encoded(pack),
                                        "request.json": intake.encoded(request),
                                        "metadata.json": intake.encoded(handoff)}, artifact_root)
            with db:
                db.execute("UPDATE tasks SET artifact=?,evidence_digest=?,request_digest=?,"
                           "handoff_digest=? WHERE candidate=?",
                           (destination.name, pack["evidence_digest"], request["request_digest"],
                            intake.digest(handoff), candidate))
            _transition(db, candidate, "request_prepared", int(time.time()))
            return {**result, "status": "request_prepared", "candidate": candidate,
                    "bundle": str(destination)}
        except (intake.IntakeError, model_contract.ContractError, StorageError):
            _transition(db, candidate, "failed", int(time.time()), "collection_or_request_failed")
            with db:
                db.execute("UPDATE tasks SET retry_after=? WHERE candidate=?",
                           (int(time.time()) + config["interval_seconds"], candidate))
            return {**result, "status": "failed", "candidate": candidate}


def status(config_path):
    config = load_config(config_path)
    with _state(config["state_root"]) as db:
        if db is None:
            return {"status": "busy"}
        handoffs = []
        for row in db.execute("SELECT repository,pr,candidate,artifact,request_digest FROM tasks"
                              " WHERE state='request_prepared' AND artifact IS NOT NULL"
                              " ORDER BY updated_at DESC LIMIT 32"):
            _require(str(UUID(row["artifact"])) == row["artifact"])
            directory = _path(Path(config["state_root"]) / "artifacts" / row["artifact"])
            if not directory.exists():
                continue
            _private_directory(directory)
            handoffs.append({"repository": row["repository"], "pr": row["pr"],
                             "candidate": row["candidate"], "request_digest": row["request_digest"],
                             "bundle": str(directory)})
        preview_status = {}
        if "preview" in config:
            from .worker_preview import status as preview_status_for
            preview_status = preview_status_for(db, Path(config["state_root"]), config["preview"])
        return {"status": "ok", "delivery_mode": "private_preview" if "preview" in config else "request_only",
                "model_calls": None if "preview" in config else 0, **preview_status,
                "github_writes": 0, "next_poll": _meta(db, "next_poll"),
                "handoffs": handoffs,
                "counts": {row["state"]: row["n"] for row in
                           db.execute("SELECT state,count(*) n FROM tasks GROUP BY state")}}
