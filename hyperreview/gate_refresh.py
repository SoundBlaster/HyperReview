"""Opt-in dispatch of a repository-owned refresh after a gate closes."""

import json
import re
import subprocess


def validate_options(options, repositories):
    from .worker import _require
    _require(type(options) is dict and 0 < len(options) <= len(repositories))
    for repository, target in options.items():
        _require(repository in repositories and type(target) is dict
                 and set(target) == {"workflow", "ref"})
        _require(type(target["workflow"]) is str
                 and re.fullmatch(r"[A-Za-z0-9_.-]+\.ya?ml", target["workflow"]) is not None
                 and type(target["ref"]) is str
                 and re.fullmatch(r"[A-Za-z0-9_.-]+", target["ref"]) is not None)


def setup(db):
    db.execute("""CREATE TABLE IF NOT EXISTS automatic_gate_refreshes (
        job TEXT PRIMARY KEY, repository TEXT NOT NULL, workflow TEXT NOT NULL,
        ref TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
        retry_after INTEGER NOT NULL DEFAULT 0, sent INTEGER NOT NULL DEFAULT 0
    )""")


def enqueue(db, config, record):
    options = config.get("gate_refresh", {})
    target = options.get(record["repository"])
    if target is None:
        return
    validate_options(options, config["review_gate"]["repositories"])
    setup(db)
    with db:
        db.execute("INSERT OR IGNORE INTO automatic_gate_refreshes(job,repository,workflow,ref) VALUES (?,?,?,?)",
                   (record["job"], record["repository"], target["workflow"], target["ref"]))


def drain(db, options, now):
    """Dispatch one completed gate; retry ambiguous failures at most twice.

    A dispatch is an idempotent refresh, not a publication. An ambiguous timeout
    can cause a duplicate workflow run, but never a duplicate review comment.
    """
    setup(db)
    row = db.execute("""SELECT r.* FROM automatic_gate_refreshes r
        JOIN automatic_review_gates g ON g.job=r.job
        WHERE r.sent=0 AND r.attempts<3 AND r.retry_after<=?
        AND g.status IN ('completed','failed_released','superseded')
        ORDER BY r.retry_after,r.job LIMIT 1""", (now,)).fetchone()
    if row is None:
        return
    target = options.get(row["repository"])
    if target != {"workflow": row["workflow"], "ref": row["ref"]}:
        return
    attempt = row["attempts"] + 1
    with db:
        db.execute("UPDATE automatic_gate_refreshes SET attempts=?,retry_after=? WHERE job=?",
                   (attempt, now + (60 if attempt == 1 else 180), row["job"]))
    try:
        result = subprocess.run(
            ["gh", "api", "--hostname", "github.com", "--method", "POST",
             f"repos/{row['repository']}/actions/workflows/{row['workflow']}/dispatches", "--input", "-"],
            input=json.dumps({"ref": row["ref"]}).encode(), capture_output=True, timeout=45, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return
    if result.returncode == 0:
        with db:
            db.execute("UPDATE automatic_gate_refreshes SET sent=1 WHERE job=?", (row["job"],))
