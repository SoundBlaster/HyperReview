"""Operator-authorized, serialized delivery of retained private previews."""

import hashlib
from itertools import islice
from pathlib import Path
import plistlib
import re
import sqlite3
import time
from uuid import UUID

from . import intake, publication, render, review_summary_link, tracking, worker, worker_preview
from .storage import StorageError, read_json, write_bundle
from .model_contract import ContractError


SCHEMA = "hyperreview.publication-worker-config.v1"
MAX_ATTEMPTS = 3
_KEYS = {"schema", "preview_config", "preview_config_sha256", "repositories",
         "mode", "interval_seconds", "state_root", "publication_state_root", "tracking"}
_TRACKING_KEYS = {"runtime_python", "database", "artifacts_root", "spool_root"}
_MUTABLE = {"metadata.json", "preview.md", "preview-compact.md"}


def load_config(path):
    path = worker._path(path)
    worker._private_file(path)
    config = read_json(path, 65536)
    worker._require(type(config) is dict and set(config) == _KEYS)
    worker._require(config["schema"] == SCHEMA and config["mode"] == "comment")
    worker._require(type(config["preview_config_sha256"]) is str
                    and publication._HEX64.fullmatch(config["preview_config_sha256"]))
    worker._require(type(config["interval_seconds"]) is int
                    and 300 <= config["interval_seconds"] <= 86400)
    repos = config["repositories"]
    worker._require(type(repos) is list and 1 <= len(repos) <= len(intake.ALLOWLIST)
                    and all(type(repo) is str and repo in intake.ALLOWLIST for repo in repos)
                    and len(repos) == len(set(repos)))
    source_path = worker._path(config["preview_config"])
    source = worker.load_config(source_path)
    worker._require("preview" in source and set(repos) <= set(source["repositories"]))
    worker._require(hashlib.sha256(source_path.read_bytes()).hexdigest()
                    == config["preview_config_sha256"])
    root, source_root = worker._path(config["state_root"]), worker._path(source["state_root"])
    worker._require(root != source_root and root not in source_root.parents
                    and source_root not in root.parents)
    worker._path(config["publication_state_root"])
    options = config["tracking"]
    worker._require(type(options) is dict and set(options) == _TRACKING_KEYS)
    for key, value in options.items():
        worker._require(type(value) is str)
        if key != "runtime_python":
            worker._path(value)
    # Only the final venv executable symlink is allowed by launchd's validator.
    from .launchd import _executable
    worker._require(Path(options["runtime_python"]).is_absolute()
                    and ".." not in Path(options["runtime_python"]).parts)
    _executable(Path(options["runtime_python"]))
    worker._require(type(config["state_root"]) is str)
    return config, source


def create_config(*, preview_config, repositories, mode, state_root, publication_state_root,
                  output_root, tracking_options,
                  interval_seconds=300):
    """This explicit operator action grants standing comment authority only."""
    path = worker._path(preview_config)
    worker._private_file(path)
    config = {"schema": SCHEMA, "preview_config": str(path),
              "preview_config_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
              "repositories": list(repositories), "mode": mode,
              "interval_seconds": interval_seconds, "state_root": str(state_root),
              "publication_state_root": str(publication_state_root),
              "tracking": {key: str(value) for key, value in tracking_options.items()}}
    # Validate a temporary private bundle before creating the operational root.
    destination = write_bundle({"config.json": intake.encoded(config)},
                               worker._private_directory(output_root, create=True))
    load_config(destination / "config.json")
    worker._prepare_logs(worker._private_directory(state_root, create=True))
    return destination


def write_launchd_plan(*, config_path, python, output_root):
    from .launchd import _absolute, _executable
    config_path, python = worker._path(config_path), _absolute(python, "Python")
    config, _ = load_config(config_path)
    _executable(python)
    root = worker._private_directory(config["state_root"], create=True)
    logs = worker._prepare_logs(root)
    plist = {"Label": "com.hyperreview.publish",
             "ProgramArguments": [str(python), "-B", "-m", "hyperreview",
                                  "publication-worker-tick", "--config", str(config_path)],
             "StartInterval": config["interval_seconds"], "RunAtLoad": False,
             "ProcessType": "Background", "Nice": 10, "LowPriorityIO": True,
             "Umask": 63, "ExitTimeOut": 10, "WorkingDirectory": str(root),
             "StandardOutPath": str(logs / "worker.stdout.log"),
             "StandardErrorPath": str(logs / "worker.stderr.log"),
             "EnvironmentVariables": {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
                                      "PYTHONDONTWRITEBYTECODE": "1"}}
    return write_bundle({"agent.plist": plistlib.dumps(plist, sort_keys=True),
                         "installation.md": b"# Publication worker\n\nThis plan can create/update one owned HyperReview comment per configured PR. When its pinned v3 source grants automatic review threads, it can also add one journaled summary link in its own completed thread.\nReview the standing repository grant, pinned preview config, MLflow paths and plist before installing as com.hyperreview.publish.\nThe generator does not install or start services. Disable/unload that label to revoke scheduled publication.\n"},
                        worker._private_directory(output_root, create=True))


def _setup(db, config):
    binding = intake.digest(config)
    previous = db.execute("SELECT value FROM metadata WHERE key='publication_grant'").fetchone()
    worker._require(previous is None or previous[0] == binding,
                    "Publication state belongs to another operator grant")
    worker._set_meta(db, "publication_grant", binding)
    db.execute("""CREATE TABLE IF NOT EXISTS deliveries (
        job TEXT PRIMARY KEY, repository TEXT NOT NULL, pr INTEGER NOT NULL,
        state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
        snapshot TEXT NOT NULL, identity_digest TEXT NOT NULL, event_digest TEXT NOT NULL,
        plan TEXT, plan_digest TEXT, comment_digest TEXT, comment_id INTEGER,
        failure_code TEXT, updated_at INTEGER NOT NULL, review_gate_url TEXT)""")
    if "review_gate_url" not in {row[1] for row in db.execute("PRAGMA table_info(deliveries)")}:
        db.execute("ALTER TABLE deliveries ADD COLUMN review_gate_url TEXT")
    review_summary_link.setup(db)
    db.commit()


def _clean_snapshot_temps(bundle):
    worker._private_directory(bundle)
    entries = list(islice(bundle.iterdir(), len(worker_preview.FILES) + 18))
    worker._require(len(entries) <= len(worker_preview.FILES) + 17)
    for path in entries:
        if re.fullmatch(r"\.tracking-[a-z0-9_]{8}", path.name):
            worker._private_file(path)
            worker._require(path.stat().st_size <= worker_preview.MAX_FILE_BYTES)
            path.unlink()


def _snapshot_identity(bundle):
    _clean_snapshot_temps(bundle)
    worker._private_directory(bundle)
    entries = list(islice(bundle.iterdir(), len(worker_preview.FILES) + 2))
    worker._require(len(entries) <= len(worker_preview.FILES) + 1
                    and worker_preview.FILES <= {p.name for p in entries}
                    <= worker_preview.FILES | {"tracking-receipt.json"})
    hashes = {}
    for path in entries:
        worker._private_file(path)
        worker._require(path.stat().st_size <= worker_preview.MAX_FILE_BYTES)
        raw = path.read_bytes()
        worker._require(len(raw) <= worker_preview.MAX_FILE_BYTES)
        if path.name in worker_preview.FILES - _MUTABLE:
            hashes[path.name] = hashlib.sha256(raw).hexdigest()
    return intake.digest(hashes)


def _snapshot_one(db, root, config, source, now):
    """Hold the upstream lock across manifest validation and immutable copying."""
    with worker._state(source["state_root"]) as upstream:
        if upstream is None:
            return None, "preview_busy"
        worker_preview._setup(upstream)
        settings = worker_preview._settings(source["preview"], source.get("review_gate"))
        rows = upstream.execute("""SELECT j.*,t.repository,t.pr FROM preview_jobs j
            JOIN tasks t ON t.candidate=j.candidate WHERE j.state='preview_ready'
            AND t.state='request_prepared' AND j.artifact IS NOT NULL AND j.settings=?
            ORDER BY j.updated_at DESC LIMIT ?""", (settings, worker.MAX_RECEIPTS)).fetchall()
        for row in rows:
            if row["repository"] not in config["repositories"]:
                continue
            if db.execute("SELECT 1 FROM deliveries WHERE job=?", (row["job"],)).fetchone():
                continue
            gate_url = None
            if "review_gate" in source:
                from .automatic_review_gate import link
                gate_url = link(upstream, row["job"])
                if row["repository"] in source["review_gate"]["repositories"]:
                    worker._require(type(gate_url) is str and gate_url,
                                    "Current gated preview lacks its automatic thread binding")
            worker._require(str(UUID(row["artifact"])) == row["artifact"])
            original = Path(source["state_root"]) / "previews" / row["artifact"]
            if not original.exists():
                continue
            worker._require(worker_preview._manifest(original) == row["bundle_digest"])
            files = {name: (original / name).read_bytes() for name in worker_preview.FILES}
            worker._require(intake.digest({name: hashlib.sha256(raw).hexdigest()
                                          for name, raw in files.items()}) == row["bundle_digest"])
            destination = write_bundle(files, worker._private_directory(root / "snapshots", create=True))
            event = tracking.build_event(destination)
            worker._require(event["metadata"]["repository"] == row["repository"]
                            and event["metadata"]["pr"] == str(row["pr"]))
            with db:
                db.execute("""INSERT INTO deliveries
                    (job,repository,pr,state,snapshot,identity_digest,event_digest,updated_at,review_gate_url)
                    VALUES (?,?,?,?,?,?,?,?,?)""",
                           (row["job"], row["repository"], row["pr"], "tracking", destination.name,
                            _snapshot_identity(destination), intake.digest(event), now, gate_url))
            return db.execute("SELECT * FROM deliveries WHERE job=?", (row["job"],)).fetchone(), None
    return None, "idle"


def _api():
    client = intake.GitHub()
    client.deadline = min(client.deadline, time.monotonic() + 60)
    return client


def _expire(db, root, now):
    """Expire terminal/orphan artifacts; retain receipts and pending operations."""
    pending = db.execute("""SELECT d.snapshot,d.plan FROM deliveries d
        LEFT JOIN review_summary_links n ON n.job=d.job
        WHERE d.state IN ('tracking','publishing','needs_attention')
        OR (d.state='published' AND d.review_gate_url IS NOT NULL
            AND (n.job IS NULL OR n.status IN ('pending','creating','checking')))""").fetchall()
    for name, allowed, field in (("snapshots", worker_preview.FILES | {"tracking-receipt.json"}, "snapshot"),
                                 ("plans", {"plan.json", "comment.md"}, "plan")):
        directory = worker._path(root / name)
        if not directory.exists():
            continue
        worker._private_directory(directory)
        entries = list(islice(directory.iterdir(), worker.MAX_RECEIPTS * 2 + 1))
        worker._require(len(entries) <= worker.MAX_RECEIPTS * 2)
        retained = {row[field] for row in pending if row[field] is not None}
        for bundle in entries:
            worker._require(str(UUID(bundle.name)) == bundle.name)
            worker._private_directory(bundle)
            if name == "snapshots":
                _clean_snapshot_temps(bundle)
            if bundle.name in retained or bundle.stat().st_mtime >= now - worker.RETENTION_SECONDS:
                continue
            files = list(islice(bundle.iterdir(), len(allowed) + 1))
            worker._require(len(files) <= len(allowed) and all(p.name in allowed for p in files))
            for path in files:
                worker._private_file(path)
            for path in files:
                path.unlink()
            bundle.rmdir()


def _refresh(bundle, receipt):
    tracking.update_bundle_tracking(bundle, receipt)
    request, result = read_json(bundle / "request.json"), read_json(bundle / "result.json", 1024 * 1024)
    compiler, diff = read_json(bundle / "compiler-receipt.json"), read_json(bundle / "diff.json", 1024 * 1024)
    tracking._atomic_bytes(bundle / "preview.md", render.render_preview(
        request, result, compiler, diff, tracking_status="confirmed"))
    tracking._atomic_bytes(bundle / "preview-compact.md", render.render_compact_preview(
        request, result, compiler, diff, tracking_status="confirmed"))


def _retryable_plan(plan):
    blockers = set(plan["blockers"])
    transient = {"github_read_failed", "final_recheck_failed", "comment_inventory_incomplete"}
    if not blockers & transient:
        return False
    definitive = {"repository_or_pr_not_allowlisted", "authenticated_account_mismatch",
                  "pr_author_mismatch", "pr_not_open", "pr_is_draft", "cross_repository_pr",
                  "pr_identity_mismatch", "pr_ineligible", "authenticated_account_changed",
                  "duplicate_own_marker_comments", "review_gate_invalid",
                  "review_gate_revision_changed", "tracking_unconfirmed", "live_revision_invalid"}
    if blockers & definitive:
        return False
    # Read failures can leave current revisions unknown, producing derived
    # mismatch blockers. A concrete observed mismatch is definitive instead.
    return not any(publication._revision(plan.get("current_" + field))
                   and plan["current_" + field] != plan[field]
                   for field in ("base_sha", "head_sha", "merge_base_sha"))


def _notify_link(db, root, config, source, delivery):
    try:
        return review_summary_link.deliver(db, root, config, source, delivery)
    except (sqlite3.Error, worker.WorkerError, StorageError, OSError, ValueError, TypeError, KeyError):
        # A completed ordinary-comment delivery stays completed if the separate
        # notification journal is temporarily unavailable.
        return "pending"


def tick(config_path):
    config, source = load_config(config_path)
    root = worker._private_directory(config["state_root"], create=True)
    now = int(time.time())
    with worker._state(root) as db:
        if db is None:
            return {"status": "busy"}
        _setup(db, config)
        worker._rotate_logs(root)
        if now < worker._meta(db, "next_poll"):
            return {"status": "not_due"}
        worker._set_meta(db, "next_poll", now + config["interval_seconds"])
        _expire(db, root, now)
        notice = review_summary_link.next_delivery(db, config, source)
        if notice is not None:
            result = _notify_link(db, root, config, source, notice)
            if result != "preview_busy":
                return {"status": "review_link_" + result, "job": notice["job"],
                        "repository": notice["repository"], "pr": notice["pr"]}
        row = db.execute("SELECT * FROM deliveries WHERE state IN ('tracking','publishing')"
                         " ORDER BY updated_at LIMIT 1").fetchone()
        if row is None:
            if db.execute("SELECT count(*) FROM deliveries").fetchone()[0] >= worker.MAX_RECEIPTS:
                return {"status": "capacity_reached"}
            row, state = _snapshot_one(db, root, config, source, now)
            if row is None:
                return {"status": state}
        job = row["job"]
        base = {"job": job, "repository": row["repository"], "pr": row["pr"]}
        try:
            worker._require(row["attempts"] < MAX_ATTEMPTS)
            with db:
                db.execute("UPDATE deliveries SET attempts=attempts+1,updated_at=? WHERE job=?", (now, job))
            worker._require(row["repository"] in config["repositories"])
            worker._require(str(UUID(row["snapshot"])) == row["snapshot"])
            bundle = root / "snapshots" / row["snapshot"]
            worker._require(_snapshot_identity(bundle) == row["identity_digest"])
            event = tracking.build_event(bundle)
            worker._require(intake.digest(event) == row["event_digest"])
            if row["state"] == "tracking":
                receipt = tracking.reconcile(event, **config["tracking"], timeout_seconds=120)
                _refresh(bundle, receipt)
                preview_digest = hashlib.sha256((bundle / "preview-compact.md").read_bytes()).hexdigest()
                directory, plan = publication.plan_publication(
                    bundle, expected_preview_sha256=preview_digest,
                    output_root=worker._private_directory(root / "plans", create=True),
                    review_gate_url=row["review_gate_url"], api=_api())
                worker._require(plan["repository"] == row["repository"] and plan["pr"] == row["pr"])
                if plan["status"] != "ready":
                    if _retryable_plan(plan):
                        raise publication.PublicationError("Publication reads temporarily unavailable")
                    with db:
                        db.execute("UPDATE deliveries SET state='blocked',failure_code='publication_gate_blocked',updated_at=? WHERE job=?", (int(time.time()), job))
                    return {**base, "status": "blocked", "blockers": plan["blockers"]}
                with db:
                    db.execute("""UPDATE deliveries SET state='publishing',plan=?,plan_digest=?,
                        comment_digest=?,updated_at=? WHERE job=?""",
                               (directory.name, hashlib.sha256((directory / "plan.json").read_bytes()).hexdigest(),
                                hashlib.sha256((directory / "comment.md").read_bytes()).hexdigest(),
                                int(time.time()), job))
                row = db.execute("SELECT * FROM deliveries WHERE job=?", (job,)).fetchone()
            worker._require(str(UUID(row["plan"])) == row["plan"])
            # Persisted exact plan is reused after uncertain writes. Never replan
            # a pending operation: the existing broker reconciles its marker.
            result = publication.publish_comment(
                root / "plans" / row["plan"], expected_plan_sha256=row["plan_digest"],
                expected_comment_sha256=row["comment_digest"],
                authorized_repository=row["repository"], authorized_mode=config["mode"],
                state_root=config["publication_state_root"], api=_api())
            state = "published" if result["status"] in ("published", "already_published") else result["status"]
            if state == "stale_reconciliation_pending":
                state = "publishing"
            with db:
                db.execute("UPDATE deliveries SET state=?,comment_id=?,failure_code=NULL,updated_at=? WHERE job=?",
                           (state, result.get("comment_id"), int(time.time()), job))
            notification = {}
            if state == "published":
                delivered = db.execute("SELECT * FROM deliveries WHERE job=?", (job,)).fetchone()
                notification["review_link_status"] = _notify_link(db, root, config, source, delivered)
            return {**base, **result, **notification,
                    "comment_url": f"https://github.com/{row['repository']}/pull/{row['pr']}#issuecomment-{result['comment_id']}"}
        except publication.PublicationBlockedBeforeWrite:
            with db:
                db.execute("UPDATE deliveries SET state='blocked',failure_code='fresh_gate_blocked',updated_at=? WHERE job=?",
                           (int(time.time()), job))
            return {**base, "status": "blocked", "failure_code": "fresh_gate_blocked"}
        except (publication.PublicationError, tracking.TrackingError, worker.WorkerError,
                StorageError, ContractError, intake.IntakeError, OSError, ValueError, KeyError, TypeError):
            attempts = db.execute("SELECT attempts FROM deliveries WHERE job=?", (job,)).fetchone()[0]
            with db:
                db.execute("UPDATE deliveries SET failure_code='delivery_failed',updated_at=?,state=CASE WHEN ? >= ? THEN 'needs_attention' ELSE state END WHERE job=?",
                           (int(time.time()), attempts, MAX_ATTEMPTS, job))
            return {**base, "status": "delivery_failed", "failure_code": "delivery_failed"}


def status(config_path):
    config, _ = load_config(config_path)
    with worker._state(config["state_root"]) as db:
        if db is None:
            return {"status": "busy"}
        _setup(db, config)
        return {"status": "ok", "repositories": config["repositories"], "mode": config["mode"],
                **review_summary_link.status(db),
                "next_poll": worker._meta(db, "next_poll"),
                "counts": {r["state"]: r["n"] for r in db.execute("SELECT state,count(*) n FROM deliveries GROUP BY state")},
                "deliveries": [dict(r) for r in db.execute("SELECT job,repository,pr,state,attempts,comment_id,failure_code,updated_at FROM deliveries ORDER BY updated_at DESC LIMIT 32")]}
