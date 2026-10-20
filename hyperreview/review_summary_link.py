"""At-most-once completion links for confirmed, journaled review publications."""

import hashlib
from pathlib import Path
import time
from uuid import UUID

from . import automatic_review_gate as gates, intake, publication, worker
from .feedback import FeedbackError, _read_bounded_regular
from .storage import StorageError, read_json


_PREFIX = "<!-- hyperreview:review-summary-link:v1:"
_PENDING = ("pending", "creating", "checking")
_MAX_READS = 3


def setup(db):
    db.execute("""CREATE TABLE IF NOT EXISTS review_summary_links (
        job TEXT PRIMARY KEY, status TEXT NOT NULL,
        mutation_attempts INTEGER NOT NULL DEFAULT 0,
        recovery_attempts INTEGER NOT NULL DEFAULT 0,
        reply_id INTEGER, failure_code TEXT, updated_at INTEGER NOT NULL)""")


def _set(db, job, **values):
    values["updated_at"] = int(time.time())
    with db:
        db.execute("UPDATE review_summary_links SET "
                   + ",".join(f"{key}=?" for key in values) + " WHERE job=?",
                   (*values.values(), job))


def _require(value, code="review_link_binding_changed"):
    if not value:
        raise gates.GateError(code)


def next_delivery(db, config, source):
    selected = set(config["repositories"]) & set(source.get("review_gate", {}).get("repositories", []))
    if not selected:
        return None
    rows = db.execute("""SELECT d.* FROM deliveries d LEFT JOIN review_summary_links n ON n.job=d.job
        WHERE d.state='published' AND d.review_gate_url IS NOT NULL
        AND (n.job IS NULL OR n.status IN ('pending','creating','checking'))
        ORDER BY d.updated_at,d.job LIMIT ?""", (worker.MAX_RECEIPTS,)).fetchall()
    return next((row for row in rows if row["repository"] in selected), None)


def _plan(root, delivery):
    _require(type(delivery["plan"]) is str and str(UUID(delivery["plan"])) == delivery["plan"])
    directory = worker._private_directory(root / "plans" / delivery["plan"])
    for name in ("plan.json", "comment.md"):
        worker._private_file(directory / name)
    raw_plan = _read_bounded_regular(directory / "plan.json", 262144)
    raw_body = _read_bounded_regular(directory / "comment.md", publication.MAX_COMMENT_BYTES)
    _require(hashlib.sha256(raw_plan).hexdigest() == delivery["plan_digest"]
             and hashlib.sha256(raw_body).hexdigest() == delivery["comment_digest"])
    plan = read_json(directory / "plan.json", 262144)
    _require(plan.get("schema") == publication.PLAN_SCHEMA and plan.get("status") == "ready"
             and plan.get("repository") == delivery["repository"] and plan.get("pr") == delivery["pr"]
             and type(plan.get("review_gate")) is dict
             and plan["review_gate"].get("url") == delivery["review_gate_url"]
             and publication._revision(plan.get("head_sha")))
    return plan


def _root(source, delivery, plan):
    with worker._state(source["state_root"]) as upstream:
        if upstream is None:
            return None
        gates._setup(upstream)
        row = upstream.execute("SELECT * FROM automatic_review_gates WHERE job=?",
                               (delivery["job"],)).fetchone()
        _require(row is not None)
        record = dict(row)
        gates._authorized(record, source)
        _require((record["repository"], record["pr"], record["url"], record["head_sha"])
                 == (delivery["repository"], delivery["pr"], delivery["review_gate_url"], plan["head_sha"]))
        _require(record["status"] == "completed" and record["completion_outcome"] == "preview_ready",
                 "review_link_gate_pending")
        _, body = gates._load_plan(record)
        return record, body


def _inventory(api, record, root_body, notice_body, marker):
    comments = gates._comments(api, record["repository"], record["pr"])
    roots = [item for item in comments if item["id"] == record["comment_id"]]
    _require(len(roots) == 1)
    root = roots[0]
    _require(root.get("user") == record["account"] and root.get("body") == root_body
             and root.get("path") == record["path"] and root.get("in_reply_to_id") is None
             and root.get("html_url") == record["url"]
             and gates._comment_id(root.get("html_url"), record["repository"], record["pr"]) == root["id"]
             and root.get("pull_request_url") == f"https://api.github.com/repos/{record['repository']}/pulls/{record['pr']}"
             and record["line"] in (root.get("line"), root.get("original_line"))
             and record["head_sha"] in (root.get("commit_id"), root.get("original_commit_id")))
    matches = [item for item in comments if item.get("user") == record["account"]
               and marker in item.get("body", "")]
    _require(len(matches) <= 1)
    if not matches:
        return None
    notice = matches[0]
    _require(notice.get("body") == notice_body and notice.get("in_reply_to_id") == record["comment_id"]
             and gates._comment_id(notice.get("html_url"), record["repository"], record["pr"]) == notice["id"])
    return notice["id"]


def _deliver(db, root, source, delivery, notice):
    plan = _plan(root, delivery)
    binding = _root(source, delivery, plan)
    if binding is None:
        _set(db, delivery["job"], recovery_attempts=notice["recovery_attempts"])
        return "preview_busy"
    record, root_body = binding
    comment_id = delivery["comment_id"]
    _require(type(comment_id) is int and comment_id > 0)
    url = f"https://github.com/{record['repository']}/pull/{record['pr']}#issuecomment-{comment_id}"
    marker = f"{_PREFIX}{record['job']} -->"
    body = (f"{marker}\n**HyperReview review published.** [Open the review summary]({url}).\n\n"
            f"Reviewed revision: `{record['head_sha']}`.")
    api = worker._gate_observation_api()
    account = gates._rest(api, "user", "{login}").get("login")
    pr = intake.metadata(api, record["repository"], record["pr"])
    # This only links an already-published result; merged PRs can be notified too.
    # It does not reopen/resolve a thread or analyze a new revision.
    _require(account == record["account"] == intake.AUTHOR and pr.get("author") == account
             and pr.get("number") == record["pr"] and pr.get("base_repo") == record["repository"]
             and pr.get("head_repo") == record["repository"] and pr.get("state") in ("open", "closed"))
    existing = _inventory(api, record, root_body, body, marker)
    if existing is not None:
        _set(db, record["job"], status="linked", reply_id=existing, failure_code=None)
        return "linked"
    if notice["mutation_attempts"]:
        _set(db, record["job"], status="checking", failure_code="review_link_write_unconfirmed")
        return "checking"
    summary = gates._rest(api, f"repos/{record['repository']}/issues/comments/{comment_id}",
                           "{id,user:.user.login,body,html_url,issue_url}")
    _require(type(summary) is dict and summary.get("id") == comment_id
             and summary.get("user") == account and summary.get("html_url") == url
             and summary.get("issue_url") == f"https://api.github.com/repos/{record['repository']}/issues/{record['pr']}"
             and type(summary.get("body")) is str
             and summary["body"].startswith(publication.COMMENT_MARKER + "\n\n"))
    _require(hashlib.sha256(summary["body"].encode()).hexdigest() == delivery["comment_digest"],
             "review_link_summary_changed")
    # Persist before a possible POST. Recovery inventories this fixed marker;
    # no second POST is allowed, even after a timeout or an interrupted response.
    _set(db, record["job"], status="creating", mutation_attempts=1, failure_code=None)
    gates._write_rest(record["repository"], record["pr"], body, reply_to=record["comment_id"])
    reply_id = _inventory(api, record, root_body, body, marker)
    _require(reply_id is not None, "review_link_write_unconfirmed")
    _set(db, record["job"], status="linked", reply_id=reply_id, failure_code=None)
    return "linked"


def deliver(db, root, config, source, delivery):
    """Isolate completion-link failures from successful summary publication."""
    selected = set(config["repositories"]) & set(source.get("review_gate", {}).get("repositories", []))
    if delivery["repository"] not in selected or not delivery["review_gate_url"]:
        return "not_granted"
    with db:
        db.execute("INSERT OR IGNORE INTO review_summary_links(job,status,updated_at) VALUES (?,'pending',?)",
                   (delivery["job"], int(time.time())))
    notice = db.execute("SELECT * FROM review_summary_links WHERE job=?", (delivery["job"],)).fetchone()
    if notice["status"] not in _PENDING:
        return notice["status"]
    if notice["recovery_attempts"] >= _MAX_READS:
        _set(db, delivery["job"], status="needs_attention", failure_code="review_link_recovery_limit")
        return "needs_attention"
    try:
        _set(db, delivery["job"], recovery_attempts=notice["recovery_attempts"] + 1)
        _require(delivery["state"] == "published")
        return _deliver(db, Path(root), source, delivery, notice)
    except (gates.GateError, worker.WorkerError, publication.PublicationError,
            intake.IntakeError, FeedbackError, StorageError, OSError, ValueError, TypeError, KeyError) as error:
        code = error.code if isinstance(error, gates.GateError) else "review_link_unavailable"
        terminal = code in ("review_link_binding_changed", "review_gate_not_granted",
                            "review_link_summary_changed", "review_gate_state_invalid")
        current = db.execute("SELECT recovery_attempts FROM review_summary_links WHERE job=?",
                             (delivery["job"],)).fetchone()[0]
        _set(db, delivery["job"], status="needs_attention" if terminal or current >= _MAX_READS else "checking",
             failure_code=code)
        return "needs_attention" if terminal or current >= _MAX_READS else "checking"


def status(db):
    return {"review_link_counts": {row["status"]: row["n"] for row in db.execute(
        "SELECT status,count(*) n FROM review_summary_links GROUP BY status")},
        "review_links": [dict(row) for row in db.execute(
            "SELECT * FROM review_summary_links ORDER BY updated_at DESC LIMIT 32")]}
