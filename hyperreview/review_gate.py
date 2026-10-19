"""Explicit creation of an unresolved, diff-anchored review gate."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import fcntl

from . import intake
from .feedback import FeedbackError, _read_bounded_regular
from .publication import (_HEX40, PublicationError, _api_get, _blockers_for_eligibility,
                          _atomic_private_json, _private_state_root, _require,
                          _safe_output_root, _safe_plan_directory)
from .storage import StorageError, read_json, write_bundle


GATE_MARKER = "<!-- hyperreview:review-gate:v1:"
GATE_PLAN_SCHEMA = "hyperreview.review-gate-plan.v1"
MAX_FILES_PAGES = 10
MAX_GATE_PAGES = 10


def _gate_comments(api, repo, number):
    result = []
    for page in range(1, MAX_GATE_PAGES + 1):
        try:
            values = api.get(
                f"repos/{repo}/pulls/{number}/comments?per_page=100&page={page}",
                "[.[]|{id,user:.user.login,body,html_url,path,line,commit_id}]",
            )
        except Exception:
            raise PublicationError("Review-gate inventory is incomplete") from None
        _require(type(values) is list and len(values) <= 100
                 and all(type(item) is dict and type(item.get("id")) is int
                         and type(item.get("user")) is str and type(item.get("body")) is str
                         for item in values))
        result.extend(values)
        if len(values) < 100:
            return result
    raise PublicationError("Review-gate inventory is incomplete")


def _files(api, repo, number):
    result = []
    for page in range(1, MAX_FILES_PAGES + 1):
        values = api.get(f"repos/{repo}/pulls/{number}/files?per_page=100&page={page}",
                         "[.[]|{filename,patch}]" )
        _require(type(values) is list and len(values) <= 100)
        result.extend(values)
        if len(values) < 100:
            return result
    raise PublicationError("Changed-file inventory is incomplete")


def _added_line(patch, target):
    if type(patch) is not str:
        return False
    old_line = new_line = None
    for row in patch.splitlines():
        match = re.match(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", row)
        if match:
            old_line, new_line = int(match.group(1)), int(match.group(2))
        elif row.startswith("+++") or row.startswith("---") or old_line is None:
            continue
        elif row.startswith("+"):
            if new_line == target:
                return True
            new_line += 1
        elif row.startswith("-"):
            old_line += 1
        else:
            old_line += 1
            new_line += 1
    return False


def _gate_body(expected_completion, gate_id):
    return (f"{GATE_MARKER}{gate_id} -->\n\n"
            "**HyperReview review started.** This unresolved review thread is the merge gate.\n\n"
            f"Expected completion: {expected_completion} (UTC).\n\n"
            "The final review summary will link back to this thread. Resolve it only after "
            "the review is complete.")


class GitHubReviewWriter:
    """Narrow writer for one new inline PR review comment; no edit/resolve methods."""

    def create(self, repo, number, *, commit_id, path, line, body):
        payload = json.dumps({"commit_id": commit_id, "path": path, "line": line,
                              "side": "RIGHT", "body": body},
                             ensure_ascii=True).encode()
        try:
            result = subprocess.run(
                ["gh", "api", "--hostname", "github.com", "--method", "POST",
                 f"repos/{repo}/pulls/{number}/comments", "--input", "-"],
                input=payload, capture_output=True, timeout=60, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise PublicationError("Review-gate write outcome is uncertain") from None
        if result.returncode != 0:
            raise PublicationError("Review-gate write failed")
        try:
            value = json.loads(result.stdout)
        except (ValueError, UnicodeError):
            raise PublicationError("Review-gate write outcome is uncertain") from None
        _require(type(value) is dict and type(value.get("id")) is int
                 and value["id"] > 0 and value.get("body") == body
                 and type(value.get("html_url")) is str
                 and value["html_url"].startswith("https://github.com/"))
        return value


def plan_review_gate(*, repository, pr_number, path, line, expected_completion,
                     output_root, api=None):
    """Save a private plan for a changed-line review thread; performs reads only."""
    _require(repository in intake.ALLOWLIST and type(pr_number) is int and pr_number > 0
             and type(path) is str and path and not path.startswith("/")
             and ".." not in path.split("/") and intake.exclusion(path) is None
             and type(line) is int and line > 0)
    try:
        deadline = datetime.fromisoformat(expected_completion.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        raise PublicationError("Expected completion must be an ISO 8601 UTC timestamp") from None
    _require(deadline.tzinfo is not None and deadline.utcoffset().total_seconds() == 0
             and deadline > datetime.now(timezone.utc))
    api = api or intake.GitHub()
    account = _api_get(api, "user", "{login}").get("login")
    pr = intake.metadata(api, repository, pr_number)
    blockers = _blockers_for_eligibility(repository, pr_number, pr, account)
    _require(not blockers and type(pr.get("head_sha")) is str
             and _HEX40.fullmatch(pr["head_sha"]) is not None)
    changed = _files(api, repository, pr_number)
    matches = [entry for entry in changed if type(entry) is dict
               and entry.get("filename") == path and _added_line(entry.get("patch"), line)]
    _require(len(matches) == 1)
    expected_utc = deadline.astimezone(timezone.utc).isoformat(timespec="minutes")
    expected_utc = expected_utc.replace("+00:00", "Z")
    gate_id = hashlib.sha256(
        f"{repository}|{pr_number}|{pr['head_sha']}|{path}|{line}|{expected_utc}".encode()
    ).hexdigest()[:20]
    body = _gate_body(expected_utc, gate_id)
    root = _safe_output_root(output_root)
    plan = {"schema": GATE_PLAN_SCHEMA, "status": "ready", "repository": repository,
            "pr": pr_number, "head_sha": pr["head_sha"], "path": path, "line": line,
            "side": "RIGHT", "expected_completion": deadline.astimezone(timezone.utc)
            .isoformat(timespec="minutes").replace("+00:00", "Z"),
            "gate_id": gate_id,
            "body_sha256": hashlib.sha256(body.encode()).hexdigest(),
            "authorization_required": True, "writes_performed": False}
    try:
        destination = write_bundle({"plan.json": intake.encoded(plan),
                                    "comment.md": body.encode()}, root)
    except (StorageError, OSError, ValueError, TypeError):
        raise PublicationError("Review-gate plan could not be saved privately") from None
    return destination, plan


def publish_review_gate(plan_dir, *, expected_plan_sha256, expected_comment_sha256,
                        authorized_repository, state_root, api=None, writer=None):
    """Create one unresolved review comment after exact local authorization."""
    for value in (expected_plan_sha256, expected_comment_sha256):
        _require(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None)
    directory = _safe_plan_directory(plan_dir)
    try:
        raw_plan = _read_bounded_regular(directory / "plan.json", 262144)
        body_bytes = _read_bounded_regular(directory / "comment.md", 65536)
        _require(hashlib.sha256(raw_plan).hexdigest() == expected_plan_sha256
                 and hashlib.sha256(body_bytes).hexdigest() == expected_comment_sha256)
        plan = json.loads(raw_plan)
        body = body_bytes.decode("utf-8")
    except (FeedbackError, OSError, ValueError, TypeError, UnicodeError):
        raise PublicationError("Reviewed review-gate artifacts are invalid") from None
    _require(type(plan) is dict and plan.get("schema") == GATE_PLAN_SCHEMA
             and plan.get("status") == "ready" and plan.get("authorization_required") is True
             and plan.get("writes_performed") is False
             and plan.get("repository") == authorized_repository
             and authorized_repository in intake.ALLOWLIST
             and type(plan.get("pr")) is int and plan["pr"] > 0
             and type(plan.get("gate_id")) is str
             and re.fullmatch(r"[0-9a-f]{20}", plan["gate_id"]) is not None
             and body.startswith(f"{GATE_MARKER}{plan['gate_id']} -->\n\n")
             and hashlib.sha256(body_bytes).hexdigest() == plan.get("body_sha256"))
    try:
        expected_completion = datetime.fromisoformat(
            plan["expected_completion"].replace("Z", "+00:00"))
    except (AttributeError, ValueError, KeyError):
        raise PublicationError("Reviewed review-gate artifacts are invalid") from None
    _require(expected_completion.tzinfo is not None
             and expected_completion.utcoffset().total_seconds() == 0
             and expected_completion > datetime.now(timezone.utc))
    root = _private_state_root(state_root)
    receipt_path = root / f"gate-{authorized_repository.replace('/', '-')}-{plan['pr']}-{plan['gate_id']}.json"
    lock_path = receipt_path.with_suffix(".lock")
    _require(not receipt_path.is_symlink() and not lock_path.is_symlink())
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR
                         | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        if receipt_path.exists():
            receipt = read_json(receipt_path, max_bytes=65536)
            _require(type(receipt) is dict and receipt.get("plan_sha256") == expected_plan_sha256
                     and type(receipt.get("html_url")) is str)
            return {"status": "already_published", "html_url": receipt["html_url"]}
        api = api or intake.GitHub()
        account = _api_get(api, "user", "{login}").get("login")
        pr = intake.metadata(api, authorized_repository, plan["pr"])
        _require(not _blockers_for_eligibility(authorized_repository, plan["pr"], pr, account)
                 and pr.get("head_sha") == plan.get("head_sha"))
        changed = _files(api, authorized_repository, plan["pr"])
        _require(any(entry.get("filename") == plan.get("path")
                     and _added_line(entry.get("patch"), plan.get("line"))
                     for entry in changed if type(entry) is dict))
        marker = f"{GATE_MARKER}{plan['gate_id']} -->"
        existing = [item for item in _gate_comments(api, authorized_repository, plan["pr"])
                    if item.get("user") == account and marker in item.get("body", "")]
        _require(len(existing) <= 1)
        if existing:
            response = existing[0]
            _require(response.get("body") == body and response.get("path") == plan["path"]
                     and response.get("line") == plan["line"]
                     and response.get("commit_id") == plan["head_sha"]
                     and type(response.get("html_url")) is str)
        else:
            writer = writer or GitHubReviewWriter()
            try:
                response = writer.create(authorized_repository, plan["pr"],
                                         commit_id=plan["head_sha"], path=plan["path"],
                                         line=plan["line"], body=body)
            except PublicationError:
                recovered = [item for item in _gate_comments(api, authorized_repository, plan["pr"])
                             if item.get("user") == account and item.get("body") == body
                             and item.get("path") == plan["path"]
                             and item.get("line") == plan["line"]
                             and item.get("commit_id") == plan["head_sha"]]
                _require(len(recovered) == 1 and type(recovered[0].get("html_url")) is str)
                response = recovered[0]
        confirmed = [item for item in _gate_comments(api, authorized_repository, plan["pr"])
                     if item.get("id") == response.get("id") and item.get("user") == account
                     and item.get("body") == body and item.get("path") == plan["path"]
                     and item.get("line") == plan["line"]
                     and item.get("commit_id") == plan["head_sha"]]
        _require(len(confirmed) == 1 and confirmed[0].get("html_url") == response.get("html_url"))
        receipt = {"schema": "hyperreview.review-gate-receipt.v1",
                   "plan_sha256": expected_plan_sha256,
                   "comment_sha256": expected_comment_sha256,
                   "comment_id": response["id"], "html_url": response["html_url"],
                   "status": "created", "created_at": datetime.now(timezone.utc)
                   .isoformat(timespec="seconds").replace("+00:00", "Z")}
        _atomic_private_json(receipt_path, receipt)
        return {"status": "created", "html_url": response["html_url"]}
    finally:
        os.close(descriptor)
