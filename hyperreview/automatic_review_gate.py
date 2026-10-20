"""Crash-safe, journaled automatic review gates for private preview jobs.

Only this module owns automatic gates. Every write is bound to a gate row in
the worker database and to the exact root review comment recorded there.
"""

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import stat
import subprocess
import time
from urllib.parse import quote, urlparse

from . import intake


class GateError(Exception):
    """Sanitized automatic-gate error with a stable code."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


_MAX_GATES = 2048
_MAX_RECOVERY = 3
_MAX_MUTATIONS = 4
_GATE_PREFIX = "<!-- hyperreview:review-gate:v1:"
_AUTO_PREFIX = "<!-- hyperreview:auto-review-job:v1:"
_REPLY_PREFIX = "<!-- hyperreview:auto-review-completion:v1:"
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_HEX40 = re.compile(r"[0-9a-f]{40}\Z")
_MAX_OUTPUT = 2 * 1024 * 1024
_GRAPHQL = """query AutomaticReviewGateThreads($owner:String!,$name:String!,$number:Int!,$after:String) {
 viewer { login } repository(owner:$owner,name:$name) { pullRequest(number:$number) {
  reviewThreads(first:100,after:$after) { nodes { id isResolved comments(first:1) { nodes {
   databaseId body path line commit { oid } originalCommit { oid } author { login }
  } } } pageInfo { hasNextPage endCursor } }
 } }
}"""
_RESOLVE = """mutation AutomaticReviewGateResolve($threadId:ID!) {
 resolveReviewThread(input:{threadId:$threadId}) { thread { id isResolved } }
}"""


def _fail(code):
    raise GateError(code)


def _private_dir(path, *, create=False, allow_missing=False):
    directory = Path(path)
    if not directory.is_absolute() or ".." in directory.parts:
        _fail("invalid_review_gate_config")
    for parent in (*reversed(directory.parents), directory):
        if parent.is_symlink():
            _fail("invalid_review_gate_config")
    if not directory.exists() and allow_missing:
        return directory
    try:
        if create:
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        info = directory.stat()
    except OSError:
        _fail("invalid_review_gate_config")
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077):
        _fail("invalid_review_gate_config")
    return directory


def validate_options(options, repositories):
    """Validate the narrow automatic-gate grant and its private artifact root."""
    if type(options) is not dict or set(options) != {"repositories", "eta_seconds", "state_root"}:
        _fail("invalid_review_gate_config")
    allowed = set(repositories) if type(repositories) in (list, tuple, set, frozenset) else set()
    values = options["repositories"]
    if (type(values) is not list or not 1 <= len(values) <= len(intake.ALLOWLIST)
            or any(type(repo) is not str or repo not in intake.ALLOWLIST or repo not in allowed
                   for repo in values)
            or len(values) != len(set(values))):
        _fail("invalid_review_gate_config")
    eta = options["eta_seconds"]
    if type(eta) is not int or not 300 <= eta <= 3600:
        _fail("invalid_review_gate_config")
    if type(options["state_root"]) is not str:
        _fail("invalid_review_gate_config")
    _private_dir(options["state_root"], allow_missing=True)
    return options


def _setup(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS automatic_review_gates (
            job TEXT PRIMARY KEY, candidate TEXT NOT NULL, repository TEXT NOT NULL,
            pr INTEGER NOT NULL, base_sha TEXT NOT NULL, head_sha TEXT NOT NULL,
            grant_repositories TEXT NOT NULL, account TEXT NOT NULL, gate_id TEXT NOT NULL,
            path TEXT NOT NULL, line INTEGER NOT NULL, expected_completion TEXT NOT NULL,
            started_at TEXT NOT NULL, plan_dir TEXT NOT NULL, plan_sha256 TEXT NOT NULL,
            comment_sha256 TEXT NOT NULL, body_sha256 TEXT NOT NULL,
            comment_id INTEGER, thread_id TEXT, url TEXT, status TEXT NOT NULL,
            mutation_attempts INTEGER NOT NULL DEFAULT 0,
            recovery_attempts INTEGER NOT NULL DEFAULT 0,
            reply_attempts INTEGER NOT NULL DEFAULT 0,
            completion_outcome TEXT, updated_at INTEGER NOT NULL, failure_code TEXT,
            grant_digest TEXT NOT NULL, superseded_by TEXT
        );
        CREATE TABLE IF NOT EXISTS automatic_gate_replies (
            job TEXT NOT NULL, outcome TEXT NOT NULL, PRIMARY KEY(job,outcome)
        );
        CREATE INDEX IF NOT EXISTS automatic_review_gates_pr
            ON automatic_review_gates(repository,pr,updated_at);
    """)


def _grant(config):
    return intake.digest(config["review_gate"])


def _authorized(record, config):
    if (record["repository"] not in config["review_gate"]["repositories"]
            or record["grant_digest"] != _grant(config)):
        _fail("review_gate_not_granted")


def _mapping(value):
    if type(value) is dict:
        return value
    try:
        return dict(value)
    except (TypeError, ValueError):
        return {}


def _job_id(job):
    if type(job) is str and job:
        if _HEX64.fullmatch(job) is None:
            _fail("invalid_review_gate_job")
        return job
    value = _mapping(job).get("job")
    if type(value) is not str or _HEX64.fullmatch(value) is None:
        _fail("invalid_review_gate_job")
    return value


def _api(api_factory):
    try:
        api = api_factory() if callable(api_factory) else intake.GitHub()
        if not hasattr(api, "get"):
            _fail("review_gate_unavailable")
        return api
    except GateError:
        raise
    except Exception:
        _fail("review_gate_unavailable")


def _rest(api, endpoint, query):
    try:
        return api.get(endpoint, query)
    except Exception:
        _fail("review_gate_unavailable")


def _identity(task):
    value = _mapping(task)
    repo, pr = value.get("repository"), value.get("pr")
    base, head = value.get("base_sha"), value.get("head_sha")
    candidate = value.get("candidate")
    if (type(repo) is not str or repo not in intake.ALLOWLIST or type(pr) is not int or pr <= 0
            or type(candidate) is not str or _HEX64.fullmatch(candidate) is None
            or type(base) is not str or _HEX40.fullmatch(base) is None
            or type(head) is not str or _HEX40.fullmatch(head) is None):
        _fail("invalid_review_gate_job")
    return candidate, repo, pr, base, head


def _fresh(api, task, *, require_revision=True):
    candidate, repo, pr_number, base, head = _identity(task)
    try:
        account = _rest(api, "user", "{login}").get("login")
        pr = intake.metadata(api, repo, pr_number)
        intake.eligible(repo, pr_number, pr, account)
    except Exception:
        _fail("review_gate_binding_changed")
    if require_revision and (pr.get("base_sha"), pr.get("head_sha")) != (base, head):
        _fail("review_gate_binding_changed")
    return account, pr


def _comments(api, repo, number):
    from .review_gate import MAX_GATE_PAGES
    result = []
    for page in range(1, MAX_GATE_PAGES + 1):
        values = _rest(api, f"repos/{repo}/pulls/{number}/comments?per_page=100&page={page}",
                       "[.[]|{id,user:.user.login,body,html_url,path,line,commit_id,"
                       "original_line,original_commit_id,pull_request_url,in_reply_to_id}]")
        if type(values) is not list or len(values) > 100 or any(
                type(item) is not dict or type(item.get("id")) is not int
                or type(item.get("user")) is not str or type(item.get("body")) is not str
                for item in values):
            _fail("review_gate_inventory_incomplete")
        result.extend(values)
        if len(values) < 100:
            return result
    _fail("review_gate_inventory_incomplete")


def _first_added_line(patch):
    if type(patch) is not str:
        return None
    old_line = new_line = None
    for row in patch.splitlines():
        match = re.match(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", row)
        if match:
            old_line, new_line = int(match.group(1)), int(match.group(2))
        elif old_line is None:
            continue
        elif row.startswith("+"):
            return new_line
        elif row.startswith("-"):
            old_line += 1
        else:
            old_line += 1
            new_line += 1
    return None


def _anchor(api, repo, number):
    from .review_gate import MAX_FILES_PAGES
    for page in range(1, MAX_FILES_PAGES + 1):
        files = _rest(api, f"repos/{repo}/pulls/{number}/files?per_page=100&page={page}",
                      "[.[]|{filename,patch}]")
        if type(files) is not list or len(files) > 100:
            _fail("review_gate_inventory_incomplete")
        for item in files:
            if type(item) is not dict or type(item.get("filename")) is not str:
                _fail("review_gate_inventory_incomplete")
            path = item["filename"]
            if intake.exclusion(path) is not None:
                continue
            line = _first_added_line(item.get("patch"))
            if line is not None and line > 0:
                return path, line
        if len(files) < 100:
            break
    _fail("review_gate_anchor_unavailable")


def _private_bytes(path, content):
    path = Path(path)
    if path.is_symlink() or not path.parent.is_dir():
        _fail("review_gate_state_invalid")
    descriptor = os.open(path, os.O_WRONLY | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0))
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(path, 0o600, follow_symlinks=False)
    except OSError:
        _fail("review_gate_state_invalid")


def _load_plan(record):
    from .storage import read_json
    from .feedback import _read_bounded_regular
    from .worker import _private_file
    directory = Path(record["plan_dir"])
    if not directory.is_absolute() or ".." in directory.parts:
        _fail("review_gate_state_invalid")
    for parent in (*reversed(directory.parents), directory):
        if parent.is_symlink():
            _fail("review_gate_state_invalid")
    try:
        _private_dir(directory)
        plan_path, body_path = directory / "plan.json", directory / "comment.md"
        _private_file(plan_path)
        _private_file(body_path)
        plan_bytes = _read_bounded_regular(plan_path, 262144)
        body_bytes = _read_bounded_regular(body_path, 65536)
        if (len(plan_bytes) > 262144 or len(body_bytes) > 65536
                or hashlib.sha256(plan_bytes).hexdigest() != record["plan_sha256"]
                or hashlib.sha256(body_bytes).hexdigest() != record["comment_sha256"]
                or hashlib.sha256(body_bytes).hexdigest() != record["body_sha256"]):
            _fail("review_gate_state_invalid")
        plan = read_json(plan_path)
        body = body_bytes.decode("utf-8")
    except GateError:
        raise
    except Exception:
        _fail("review_gate_state_invalid")
    if (type(plan) is not dict or plan.get("gate_id") != record["gate_id"]
            or plan.get("repository") != record["repository"] or plan.get("pr") != record["pr"]
            or plan.get("head_sha") != record["head_sha"] or plan.get("path") != record["path"]
            or plan.get("line") != record["line"]
            or not body.startswith(f"{_GATE_PREFIX}{record['gate_id']} -->\n")
            or f"{_AUTO_PREFIX}{record['job']} -->" not in body):
        _fail("review_gate_state_invalid")
    return plan, body


def _graphql(query, variables, *, expected_account=None, timeout=45, mutation=False):
    payload = json.dumps({"query": query, "variables": variables},
                         ensure_ascii=True, separators=(",", ":")).encode()
    try:
        process = subprocess.Popen(["gh", "api", "--hostname", "github.com", "graphql", "--input", "-"],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE)
    except OSError:
        _fail("review_gate_unavailable")
    streams = selectors.DefaultSelector()
    output = {process.stdout: bytearray(), process.stderr: bytearray()}
    started = time.monotonic()
    try:
        try:
            process.stdin.write(payload)
            process.stdin.close()
        except OSError:
            _fail("review_gate_unavailable")
        for stream in output:
            os.set_blocking(stream.fileno(), False)
            streams.register(stream, selectors.EVENT_READ)
        while streams.get_map():
            remaining = started + timeout - time.monotonic()
            if remaining <= 0:
                _fail("review_gate_unavailable")
            for key, _ in streams.select(min(remaining, 1)):
                chunk = os.read(key.fileobj.fileno(), 65536)
                if not chunk:
                    streams.unregister(key.fileobj)
                    continue
                output[key.fileobj].extend(chunk)
                if sum(map(len, output.values())) > _MAX_OUTPUT:
                    _fail("review_gate_inventory_incomplete")
        if process.wait(timeout=max(0.1, started + timeout - time.monotonic())) != 0:
            _fail("review_gate_unavailable")
        value = json.loads(output[process.stdout])
        if type(value) is not dict or value.get("errors"):
            _fail("review_gate_inventory_incomplete")
        data = value.get("data")
        if type(data) is not dict:
            _fail("review_gate_binding_changed")
        if not mutation and (type(data.get("viewer")) is not dict
                or (expected_account is not None and data["viewer"].get("login") != expected_account)):
            _fail("review_gate_binding_changed")
        return data
    except GateError:
        raise
    except (OSError, ValueError, subprocess.TimeoutExpired):
        _fail("review_gate_unavailable")
    finally:
        streams.close()
        if process.poll() is None:
            process.kill()
            process.wait()
        process.stdout.close()
        process.stderr.close()


def _thread_pages(repo, number, account):
    owner, name = repo.split("/", 1)
    cursor = None
    result = []
    for _ in range(10):
        data = _graphql(_GRAPHQL, {"owner": owner, "name": name,
                                  "number": number, "after": cursor},
                        expected_account=account)
        try:
            pr = data["repository"]["pullRequest"]
            connection = pr["reviewThreads"]
            nodes, page = connection["nodes"], connection["pageInfo"]
        except (TypeError, KeyError):
            _fail("review_gate_inventory_incomplete")
        if type(nodes) is not list or len(nodes) > 100:
            _fail("review_gate_inventory_incomplete")
        result.extend(nodes)
        if page.get("hasNextPage") is not True:
            return result
        cursor = page.get("endCursor")
        if type(cursor) is not str or not cursor:
            _fail("review_gate_inventory_incomplete")
    _fail("review_gate_inventory_incomplete")


def _require_resolution_rules(api, repo, pr_number, selected_repositories,
                              expected_account=None):
    identity = _rest(api, "user", "{login}")
    account = identity.get("login") if type(identity) is dict else None
    if (type(account) is not str or not account
            or (expected_account is not None and account != expected_account)):
        _fail("review_gate_binding_changed")
    target_info = _rest(api, f"repos/{repo}/pulls/{pr_number}", "{base_ref:.base.ref}")
    target = target_info.get("base_ref") if type(target_info) is dict else None
    if type(target) is not str or not target:
        _fail("review_gate_binding_changed")
    if repo not in selected_repositories or account != intake.AUTHOR:
        _fail("review_gate_binding_changed")
    encoded_branch = quote(target, safe="")
    try:
        rules = _rest(api, f"repos/{repo}/rules/branches/{encoded_branch}",
                      "[.[]|{type,parameters}]")
        if type(rules) is not list or len(rules) > 1000:
            _fail("review_gate_inventory_incomplete")
        if any(type(rule) is dict and rule.get("type") == "pull_request"
               and type(rule.get("parameters")) is dict
               and rule["parameters"].get("required_review_thread_resolution") is True
               for rule in rules):
            return
    except GateError:
        pass
    # Classic branch protection and repository/organization rulesets are
    # independent GitHub mechanisms; either effective requirement is sufficient.
    try:
        classic = _rest(api, f"repos/{repo}/branches/{encoded_branch}/protection",
                        "{required:.required_conversation_resolution.enabled}")
        if type(classic) is dict and classic.get("required") is True:
            return
    except GateError:
        pass
    _fail("review_gate_resolution_rule_missing")


def _bound_thread(record, api, *, must_be_unresolved=True, allow_outdated=False):
    record = _mapping(record)
    account, _ = _fresh(api, {"candidate": record["candidate"],
                              "repository": record["repository"], "pr": record["pr"],
                              "base_sha": record["base_sha"], "head_sha": record["head_sha"]},
                       require_revision=False)
    comments = _comments(api, record["repository"], record["pr"])
    roots = [item for item in comments if item.get("id") == record["comment_id"]]
    if len(roots) != 1:
        _fail("review_gate_binding_changed")
    root = roots[0]
    _, body = _load_plan(record)
    expected_pr_url = f"https://api.github.com/repos/{record['repository']}/pulls/{record['pr']}"
    expected_url = record.get("url")
    rest_line_ok = (root.get("line") == record["line"]
                    or (allow_outdated and root.get("original_line") == record["line"]))
    rest_commit_ok = (root.get("commit_id") == record["head_sha"]
                      or (allow_outdated and root.get("original_commit_id") == record["head_sha"]))
    if (root.get("user") != account or root.get("body") != body
            or root.get("path") != record["path"] or not rest_line_ok
            or not rest_commit_ok
            or root.get("pull_request_url") != expected_pr_url
            or root.get("html_url") != expected_url or root.get("in_reply_to_id") is not None):
        _fail("review_gate_binding_changed")
    threads = [thread for thread in _thread_pages(record["repository"], record["pr"], account)
               if type(thread) is dict and type(thread.get("comments")) is dict
               and type(thread["comments"].get("nodes")) is list
               and len(thread["comments"]["nodes"]) == 1
               and thread["comments"]["nodes"][0].get("databaseId") == record["comment_id"]]
    if len(threads) != 1:
        _fail("review_gate_binding_changed")
    thread, comment = threads[0], threads[0]["comments"]["nodes"][0]
    commit, original = comment.get("commit"), comment.get("originalCommit")
    author = comment.get("author")
    commits = {commit.get("oid") if type(commit) is dict else None,
               original.get("oid") if type(original) is dict else None}
    if ((record.get("thread_id") is not None and thread.get("id") != record["thread_id"])
            or type(author) is not dict or author.get("login") != account
            or comment.get("body") != body or comment.get("path") != record["path"]
            or (comment.get("line") != record["line"] and not allow_outdated)
            or record["head_sha"] not in commits
            or type(thread.get("isResolved")) is not bool
            or (must_be_unresolved and thread["isResolved"])):
        _fail("review_gate_binding_changed")
    return thread["id"], account, thread["isResolved"]


def _comment_url(repo, number, comment_id):
    return f"https://github.com/{repo}/pull/{number}#discussion_r{comment_id}"


def _comment_id(url, repository=None, number=None):
    parsed = urlparse(url if type(url) is str else "")
    match = re.fullmatch(r"discussion_r([1-9][0-9]*)", parsed.fragment)
    if (parsed.scheme != "https" or parsed.netloc != "github.com" or parsed.query
            or not match):
        _fail("review_gate_binding_changed")
    if repository is not None and (parsed.path != f"/{repository}/pull/{number}"):
        _fail("review_gate_binding_changed")
    return int(match.group(1))


def _write_rest(repo, number, body, *, reply_to=None):
    payload = {"body": body}
    if reply_to is not None:
        payload["in_reply_to"] = reply_to
    try:
        process = subprocess.run(
            ["gh", "api", "--hostname", "github.com", "--method", "POST",
             f"repos/{repo}/pulls/{number}/comments", "--input", "-"],
            input=json.dumps(payload, ensure_ascii=True).encode(), capture_output=True,
            timeout=45, check=False)
    except (OSError, subprocess.TimeoutExpired):
        _fail("review_gate_write_uncertain")
    if process.returncode != 0:
        _fail("review_gate_write_uncertain")
    try:
        value = json.loads(process.stdout)
    except (ValueError, UnicodeError):
        _fail("review_gate_write_uncertain")
    if type(value) is not dict or type(value.get("id")) is not int:
        _fail("review_gate_write_uncertain")
    return value


def _set(db, job, **values):
    values["updated_at"] = int(time.time())
    names = tuple(values)
    with db:
        db.execute("UPDATE automatic_review_gates SET "
                   + ",".join(f"{name}=?" for name in names) + " WHERE job=?",
                   tuple(values[name] for name in names) + (job,))


def _recover_creation(db, record, api, *, allow_outdated=False, allow_resolved=False):
    """Read-only recovery; never repeats a root-comment POST."""
    if record["recovery_attempts"] >= _MAX_RECOVERY:
        _set(db, record["job"], status="needs_attention", failure_code="recovery_limit")
        _fail("review_gate_write_uncertain")
    _set(db, record["job"], recovery_attempts=record["recovery_attempts"] + 1)
    _, body = _load_plan(record)
    account, _ = _fresh(api, {"candidate": record["candidate"],
                              "repository": record["repository"], "pr": record["pr"],
                              "base_sha": record["base_sha"], "head_sha": record["head_sha"]},
                         require_revision=not allow_outdated)
    comments = _comments(api, record["repository"], record["pr"])
    marker = f"{_AUTO_PREFIX}{record['job']} -->"
    matches = [item for item in comments if item.get("user") == account
               and marker in item.get("body", "")]
    if len(matches) != 1 or matches[0].get("body") != body:
        _set(db, record["job"], status="needs_attention", failure_code="creation_unconfirmed")
        _fail("review_gate_write_uncertain")
    url = matches[0].get("html_url")
    comment_id = _comment_id(url, record["repository"], record["pr"])
    if matches[0].get("id") != comment_id:
        _set(db, record["job"], status="needs_attention", failure_code="creation_unconfirmed")
        _fail("review_gate_write_uncertain")
    _set(db, record["job"], comment_id=comment_id, url=url, status="checking")
    current = db.execute("SELECT * FROM automatic_review_gates WHERE job=?",
                         (record["job"],)).fetchone()
    thread_id, _, _ = _bound_thread(current, api, must_be_unresolved=not allow_resolved,
                                    allow_outdated=allow_outdated)
    _set(db, record["job"], thread_id=thread_id, status="open", failure_code=None)
    return url


def _persist_plan(db, task, job_id, config, api, root):
    from .publication import _atomic_private_json
    from .review_gate import plan_review_gate
    candidate, repo, number, base, head = _identity(task)
    options = config["review_gate"]
    if repo not in options["repositories"]:
        _fail("review_gate_not_granted")
    state_root = _private_dir(options["state_root"], create=True)
    account, pr = _fresh(api, task)
    _require_resolution_rules(api, repo, number, options["repositories"], account)
    path, line = _anchor(api, repo, number)
    started = datetime.now(timezone.utc).replace(microsecond=0)
    expected = started + timedelta(seconds=options["eta_seconds"])
    expected_text = expected.isoformat(timespec="seconds").replace("+00:00", "Z")
    plan_root = state_root / "automatic-review-gate-plans"
    try:
        plan_dir, plan = plan_review_gate(
            repository=repo, pr_number=number, path=path, line=line,
            expected_completion=expected_text, output_root=plan_root, api=api)
        body_path = plan_dir / "comment.md"
        body = body_path.read_bytes().decode("utf-8")
        # Give each job a distinct marker so an automatic gate can never be
        # confused with a manually-created gate for the same candidate.
        automatic_gate_id = hashlib.sha256(
            f"{plan['gate_id']}|{job_id}".encode("utf-8")).hexdigest()[:20]
        body, replacements = re.subn(
            rf"(?m)^({_GATE_PREFIX})[a-f0-9]+ -->$",
            rf"\g<1>{automatic_gate_id} -->", body, count=1)
        if replacements != 1:
            _fail("review_gate_state_invalid")
        plan["gate_id"] = automatic_gate_id
        start_text = started.isoformat(timespec="seconds").replace("+00:00", "Z")
        body = (body.replace("\n\n**HyperReview review started.**",
                              f"\n\n{_AUTO_PREFIX}{job_id} -->\n\n"
                              f"**HyperReview automatic review started {start_text} (UTC).**")
                .replace("Expected completion:", "Informational ETA:"))
        plan["body_sha256"] = hashlib.sha256(body.encode("utf-8")).hexdigest()
        _private_bytes(body_path, body.encode("utf-8"))
        _atomic_private_json(plan_dir / "plan.json", plan)
        plan_bytes = (plan_dir / "plan.json").read_bytes()
        body_bytes = (plan_dir / "comment.md").read_bytes()
    except GateError:
        raise
    except Exception:
        _fail("review_gate_state_invalid")
    plan_digest = hashlib.sha256(plan_bytes).hexdigest()
    body_digest = hashlib.sha256(body_bytes).hexdigest()
    if len(body_bytes) > 65536 or len(plan_bytes) > 262144:
        _fail("review_gate_state_invalid")
    grant = json.dumps(options["repositories"], separators=(",", ":"))
    started_text = started.isoformat(timespec="seconds").replace("+00:00", "Z")
    with db:
        count = db.execute("SELECT count(*) FROM automatic_review_gates").fetchone()[0]
        if count >= _MAX_GATES:
            _fail("review_gate_capacity_reached")
        try:
            db.execute("""INSERT INTO automatic_review_gates
                (job,candidate,repository,pr,base_sha,head_sha,grant_repositories,account,
                 gate_id,path,line,expected_completion,started_at,plan_dir,plan_sha256,
                 comment_sha256,body_sha256,status,updated_at,grant_digest)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (job_id,candidate,repo,number,base,head,grant,account,plan["gate_id"],path,
                 line,expected_text,started_text,str(plan_dir),plan_digest,body_digest,
                 body_digest,"planned",int(time.time()),_grant(config)))
        except Exception:
            _fail("review_gate_state_invalid")
    return db.execute("SELECT * FROM automatic_review_gates WHERE job=?", (job_id,)).fetchone()


def ensure(db, root, config, task, job, api_factory=None):
    """Create or safely recover this job's unresolved root gate before inference."""
    _setup(db)
    options = config.get("review_gate") if type(config) is dict else None
    repositories = config.get("repositories", []) if type(config) is dict else []
    validate_options(options, repositories)
    _private_dir(root)
    job_id = _job_id(job)
    candidate, repo, number, base, head = _identity(task)
    if repo not in options["repositories"]:
        _fail("review_gate_not_granted")
    job_data = _mapping(job)
    if job_data.get("candidate", candidate) != candidate:
        _fail("invalid_review_gate_job")
    record = db.execute("SELECT * FROM automatic_review_gates WHERE job=?", (job_id,)).fetchone()
    api = _api(api_factory)
    if record is not None:
        _authorized(record, config)
        if (record["candidate"], record["repository"], record["pr"],
                record["base_sha"], record["head_sha"], record["grant_repositories"]) != (
                candidate, repo, number, base, head,
                json.dumps(options["repositories"], separators=(",", ":"))):
            _fail("review_gate_binding_changed")
        if record["status"] == "planned" and record["mutation_attempts"] == 0:
            pass
        elif record["status"] in ("creating", "checking", "needs_attention"):
            return _recover_creation(db, record, api)
        elif record["url"] and record["status"] == "open":
            thread_id, _, _ = _bound_thread(record, api)
            if record["thread_id"] != thread_id:
                _fail("review_gate_binding_changed")
            return record["url"]
        else:
            _fail("review_gate_state_invalid")
    else:
        record = _persist_plan(db, task, job_id, config, api, root)
    # Persist the at-most-once marker before entering the publisher that may POST.
    _set(db, job_id, status="creating", mutation_attempts=1, failure_code=None)
    record = db.execute("SELECT * FROM automatic_review_gates WHERE job=?", (job_id,)).fetchone()
    try:
        from .review_gate import publish_review_gate
        published = publish_review_gate(
            record["plan_dir"], expected_plan_sha256=record["plan_sha256"],
            expected_comment_sha256=record["comment_sha256"],
            authorized_repository=repo,
            state_root=Path(options["state_root"]) / "automatic-review-gate-receipts", api=api)
        url = published.get("html_url")
        comment_id = _comment_id(url, repo, number)
        _set(db, job_id, url=url, comment_id=comment_id, status="checking")
        record = db.execute("SELECT * FROM automatic_review_gates WHERE job=?", (job_id,)).fetchone()
        _fresh(api, task)
        thread_id, _, _ = _bound_thread(record, api)
        _set(db, job_id, thread_id=thread_id, status="open", failure_code=None)
        return url
    except GateError:
        raise
    except Exception:
        # Whether a POST occurred is unknown: only read-only recovery is safe.
        record = db.execute("SELECT * FROM automatic_review_gates WHERE job=?", (job_id,)).fetchone()
        try:
            return _recover_creation(db, record, api)
        except GateError:
            raise


def _reply_body(record, outcome):
    marker = f"{_REPLY_PREFIX}{record['job']}:{outcome} -->"
    if outcome == "preview_ready":
        message = "HyperReview analysis completed and a validated preview is available. The review summary is published after its publication checks."
    elif outcome == "stale":
        message = "This HyperReview analysis no longer matches the pull request revisions. It cannot release the review gate."
    elif outcome == "replacement_completed":
        message = "A newer HyperReview analysis for this pull request completed successfully. This earlier review gate can be released."
    else:
        message = "This HyperReview analysis failed before completion. The failure does not release the review gate."
    return f"{marker}\n{message}"


def _find_reply(record, api, body, marker):
    comments = _comments(api, record["repository"], record["pr"])
    found = [item for item in comments if item.get("user") == record["account"]
             and marker in item.get("body", "")]
    if len(found) > 1 or (found and (found[0].get("body") != body
                                    or found[0].get("in_reply_to_id") != record["comment_id"])):
        _fail("review_gate_binding_changed")
    if found and (type(found[0].get("id")) is not int
                  or _comment_id(found[0].get("html_url"), record["repository"], record["pr"])
                  != found[0]["id"]):
        _fail("review_gate_binding_changed")
    return found[0] if found else None


def _reply_once(db, record, api, outcome):
    body = _reply_body(record, outcome)
    marker = f"{_REPLY_PREFIX}{record['job']}:{outcome} -->"
    found = _find_reply(record, api, body, marker)
    if found:
        return found
    if (db.execute("SELECT 1 FROM automatic_gate_replies WHERE job=? AND outcome=?",
                   (record["job"], outcome)).fetchone() is not None
            or record["mutation_attempts"] >= _MAX_MUTATIONS):
        _set(db, record["job"], status="needs_attention", failure_code="reply_unconfirmed")
        _fail("review_gate_write_uncertain")
    with db:
        db.execute("INSERT INTO automatic_gate_replies VALUES (?,?)", (record["job"], outcome))
        db.execute("UPDATE automatic_review_gates SET reply_attempts=reply_attempts+1,"
                   " mutation_attempts=mutation_attempts+1,updated_at=? WHERE job=?",
                   (int(time.time()), record["job"]))
    try:
        _write_rest(record["repository"], record["pr"], body,
                    reply_to=record["comment_id"])
    except GateError:
        # No retry; the next reconciliation inventories by this fixed marker.
        _set(db, record["job"], status="needs_attention", failure_code="reply_outcome_uncertain")
        raise
    try:
        confirmed = _find_reply(record, api, body, marker)
    except GateError:
        _set(db, record["job"], status="needs_attention", failure_code="reply_unconfirmed")
        raise
    if confirmed is None:
        _set(db, record["job"], status="needs_attention", failure_code="reply_unconfirmed")
        _fail("review_gate_write_uncertain")
    return confirmed


def _resolve(db, record, *, superseded=False):
    if record["mutation_attempts"] >= _MAX_MUTATIONS:
        _set(db, record["job"], status="needs_attention", failure_code="mutation_limit")
        _fail("review_gate_write_uncertain")
    _set(db, record["job"], mutation_attempts=record["mutation_attempts"] + 1)
    data = _graphql(_RESOLVE, {"threadId": record["thread_id"]},
                    mutation=True)
    try:
        thread = data["resolveReviewThread"]["thread"]
    except (TypeError, KeyError):
        _fail("review_gate_write_uncertain")
    if thread.get("id") != record["thread_id"] or thread.get("isResolved") is not True:
        _fail("review_gate_write_uncertain")
    _set(db, record["job"], status="superseded" if superseded else "completed",
         completion_outcome="replacement_completed" if superseded else "preview_ready",
         failure_code=None)


def _mark_resolved_after_recovery(db, record, api):
    """Confirm an already-resolved thread has this job's exact success reply."""
    marker = f"{_REPLY_PREFIX}{record['job']}:preview_ready -->"
    matches = [item for item in _comments(api, record["repository"], record["pr"])
               if item.get("user") == record["account"] and marker in item.get("body", "")]
    expected = _reply_body(record, "preview_ready")
    if (len(matches) != 1 or matches[0].get("body") != expected
            or matches[0].get("in_reply_to_id") != record["comment_id"]):
        _fail("review_gate_binding_changed")
    if (type(matches[0].get("id")) is not int
            or _comment_id(matches[0].get("html_url"), record["repository"], record["pr"])
            != matches[0]["id"]):
        _fail("review_gate_binding_changed")
    _set(db, record["job"], status="completed", completion_outcome="preview_ready",
         reply_attempts=max(record["reply_attempts"], 1), failure_code=None)
    return record["url"]


def _schedule_older(db, record):
    # Scheduling is local and durable; later ticks finish one older thread each.
    with db:
        db.execute("UPDATE automatic_review_gates SET status='superseding',superseded_by=?,"
                   " recovery_attempts=0,updated_at=? WHERE repository=? AND pr=? AND job!=?"
                   " AND status NOT IN ('completed','superseded')"
                   " AND (superseded_by IS NULL OR superseded_by!=?)",
                   (record["job"], int(time.time()), record["repository"], record["pr"],
                    record["job"], record["job"]))


def _finish_older(db, record, config, api):
    current = db.execute("SELECT g.* FROM automatic_review_gates g JOIN preview_jobs j ON j.job=g.job"
                         " WHERE g.job=? AND g.status='completed' AND j.state='preview_ready'",
                         (record["superseded_by"],)).fetchone()
    if current is None:
        _fail("review_gate_preview_not_committed")
    _authorized(current, config)
    if (record["repository"], record["pr"]) != (current["repository"], current["pr"]):
        _fail("review_gate_binding_changed")
    task = {key: current[key] for key in ("candidate", "repository", "pr", "base_sha", "head_sha")}
    _fresh(api, task)
    if record["comment_id"] is None:
        if record["mutation_attempts"] == 0:
            _set(db, record["job"], status="superseded", completion_outcome="no_remote_gate")
            return
        _recover_creation(db, record, api, allow_outdated=True, allow_resolved=True)
        _set(db, record["job"], status="superseding")
        record = db.execute("SELECT * FROM automatic_review_gates WHERE job=?", (record["job"],)).fetchone()
    thread_id, _, resolved = _bound_thread(record, api, must_be_unresolved=False, allow_outdated=True)
    if thread_id != record["thread_id"]:
        _fail("review_gate_binding_changed")
    if resolved:
        _set(db, record["job"], status="superseded", completion_outcome="replacement_completed", failure_code=None)
        return
    _reply_once(db, record, api, "replacement_completed")
    record = db.execute("SELECT * FROM automatic_review_gates WHERE job=?", (record["job"],)).fetchone()
    _fresh(api, task)
    _bound_thread(record, api, allow_outdated=True)
    _resolve(db, record, superseded=True)


def complete(db, root, config, task, job, outcome, api_factory=None):
    """Record a terminal result; resolve only a committed successful preview."""
    _setup(db)
    options = config.get("review_gate") if type(config) is dict else None
    validate_options(options, config.get("repositories", []))
    job_id = _job_id(job)
    record = db.execute("SELECT * FROM automatic_review_gates WHERE job=?", (job_id,)).fetchone()
    if record is None:
        return None
    _authorized(record, config)
    candidate, repo, number, base, head = _identity(task)
    if (record["candidate"], record["repository"], record["pr"], record["base_sha"],
            record["head_sha"]) != (candidate, repo, number, base, head):
        _fail("review_gate_binding_changed")
    if isinstance(outcome, dict):
        outcome = outcome.get("status")
    normalized = {"success": "preview_ready", "failed": "failed", "preview_failed": "failed",
                  "preview_stale": "stale", "stale": "stale", "preview_ready": "preview_ready"}.get(outcome)
    if normalized is None:
        _fail("invalid_review_gate_outcome")
    preview = db.execute("SELECT state FROM preview_jobs WHERE job=?", (job_id,)).fetchone()
    if normalized == "preview_ready" and (preview is None or preview["state"] != "preview_ready"):
        _fail("review_gate_preview_not_committed")
    if normalized == "failed" and (preview is None or preview["state"] != "failed"):
        _fail("review_gate_preview_not_committed")
    if normalized == "stale" and (preview is None or preview["state"] != "stale"):
        _fail("review_gate_preview_not_committed")
    api = _api(api_factory)
    thread_id, account, is_resolved = _bound_thread(
        record, api, must_be_unresolved=normalized != "preview_ready",
        allow_outdated=normalized != "preview_ready")
    if record["thread_id"] != thread_id or record["account"] != account:
        _fail("review_gate_binding_changed")
    if normalized == "preview_ready":
        # Success requires a current eligibility and revision observation.
        _fresh(api, task)
        _require_resolution_rules(api, repo, number, options["repositories"], account)
        if is_resolved:
            if record["status"] in ("completing", "completed"):
                url = _mark_resolved_after_recovery(db, record, api)
                _schedule_older(db, record)
                return url
            _fail("review_gate_binding_changed")
    _reply_once(db, record, api, normalized)
    _set(db, job_id, completion_outcome=normalized,
         status="completing" if normalized == "preview_ready" else normalized)
    if normalized == "preview_ready":
        record = db.execute("SELECT * FROM automatic_review_gates WHERE job=?", (job_id,)).fetchone()
        _fresh(api, task)
        _bound_thread(record, api)
        _resolve(db, record)
        record = db.execute("SELECT * FROM automatic_review_gates WHERE job=?", (job_id,)).fetchone()
        _schedule_older(db, record)
    return record["url"]


def reconcile(db, root, config, api_factory=None):
    """Reconcile at most one pending gate operation; never invokes a model."""
    _setup(db)
    options = config.get("review_gate") if type(config) is dict else None
    validate_options(options, config.get("repositories", []))
    api = _api(api_factory)
    placeholders = ",".join("?" for _ in options["repositories"])
    rows = db.execute("""SELECT g.*,t.repository task_repository,t.pr task_pr,
                       t.base_sha task_base_sha,t.head_sha task_head_sha,t.state task_state,
                       j.state preview_state,j.candidate preview_candidate
                       FROM automatic_review_gates g
                       LEFT JOIN tasks t ON t.candidate=g.candidate
                       LEFT JOIN preview_jobs j ON j.job=g.job
                       WHERE g.repository IN (""" + placeholders + ") ORDER BY g.updated_at LIMIT ?",
                      (*options["repositories"], _MAX_GATES)).fetchall()
    row = None
    for item in rows:
        if item["recovery_attempts"] >= _MAX_RECOVERY:
            continue
        if item["superseded_by"] and item["status"] in ("superseding", "needs_attention"):
            replacement = db.execute("SELECT grant_digest FROM automatic_review_gates WHERE job=?",
                                     (item["superseded_by"],)).fetchone()
            if replacement is not None and replacement["grant_digest"] == _grant(config):
                row = item
                break
            continue
        if item["grant_digest"] != _grant(config):
            continue
        terminal = item["preview_state"] in ("preview_ready", "failed", "stale")
        actionable = (item["status"] in ("creating", "checking")
                      or (item["status"] == "planned" and item["preview_state"] == "queued")
                      or (item["status"] == "needs_attention" and terminal)
                      or (item["status"] in ("open", "completing") and terminal)
                      or (item["status"] in ("failed", "stale")
                          and item["completion_outcome"] is None and terminal))
        if actionable:
            row = item
            break
    if row is None:
        # Resume supersession scheduling even if the current root was already
        # committed completed before the process stopped. No remote effects here.
        current = next((item for item in reversed(rows)
                        if item["status"] == "completed" and item["preview_state"] == "preview_ready"
                        and item["grant_digest"] == _grant(config)
                        and db.execute("SELECT 1 FROM automatic_review_gates WHERE repository=? AND pr=?"
                                       " AND job!=? AND status NOT IN ('completed','superseded')"
                                       " AND (superseded_by IS NULL OR superseded_by!=?) LIMIT 1",
                                       (item["repository"], item["pr"], item["job"], item["job"])).fetchone()), None)
        if current is None:
            return {"reconciled": 0, "pending": 0}
        _schedule_older(db, current)
        return {"reconciled": 1, "pending": 1}
    task = {"candidate": row["candidate"], "repository": row["repository"], "pr": row["pr"],
            "base_sha": row["base_sha"], "head_sha": row["head_sha"]}
    try:
        if row["superseded_by"]:
            _set(db, row["job"], recovery_attempts=row["recovery_attempts"] + 1)
            _finish_older(db, row, config, api)
            return {"reconciled": 1, "pending": 0}
        _authorized(row, config)
        if row["status"] == "planned":
            if row["mutation_attempts"] == 0:
                ensure(db, root, config, task, row["job"], api_factory=lambda: api)
            else:
                _recover_creation(db, row, api)
        elif row["status"] in ("creating", "checking"):
            _recover_creation(db, row, api, allow_outdated=row["preview_state"] in ("failed", "stale"))
        elif row["status"] == "needs_attention" and row["comment_id"] is None:
            _recover_creation(db, row, api, allow_outdated=row["preview_state"] in ("failed", "stale"))
        elif row["status"] == "needs_attention" and row["preview_state"] in (
                "preview_ready", "failed", "stale"):
            _set(db, row["job"], recovery_attempts=row["recovery_attempts"] + 1)
            complete(db, root, config, task, row["job"], row["preview_state"],
                     api_factory=lambda: api)
        elif row["status"] in ("open", "completing") and row["preview_state"] == "preview_ready":
            _set(db, row["job"], recovery_attempts=row["recovery_attempts"] + 1)
            complete(db, root, config, task, row["job"], "preview_ready", api_factory=lambda: api)
        elif row["status"] == "open" and row["preview_state"] in ("failed", "stale"):
            _set(db, row["job"], recovery_attempts=row["recovery_attempts"] + 1)
            complete(db, root, config, task, row["job"], row["preview_state"], api_factory=lambda: api)
        elif row["status"] in ("failed", "stale") and row["reply_attempts"] == 0:
            if row["preview_state"] == row["status"]:
                _set(db, row["job"], recovery_attempts=row["recovery_attempts"] + 1)
                complete(db, root, config, task, row["job"], row["preview_state"],
                         api_factory=lambda: api)
    except GateError:
        return {"reconciled": 1, "pending": 1}
    return {"reconciled": 1, "pending": 0}


def status(db):
    """Return bounded, credential-free journal status."""
    _setup(db)
    counts = {row["status"]: row["count"] for row in db.execute(
        "SELECT status,count(*) count FROM automatic_review_gates GROUP BY status")}
    gates = [dict(row) for row in db.execute(
        """SELECT job,repository,pr,head_sha,status,url,mutation_attempts,recovery_attempts,
                  reply_attempts,updated_at,failure_code FROM automatic_review_gates
           ORDER BY updated_at DESC LIMIT 32""")]
    return {"review_gate_counts": counts, "review_gates": gates}


def link(db, job):
    """Return a validated automatic gate URL for a preview job, if journaled."""
    _setup(db)
    try:
        row = db.execute("SELECT * FROM automatic_review_gates WHERE job=?", (_job_id(job),)).fetchone()
    except GateError:
        raise
    if row is None or not row["url"]:
        return None
    comment_id = _comment_id(row["url"], row["repository"], row["pr"])
    if (row["comment_id"] != comment_id or row["status"] not in
            ("open", "completed", "failed", "stale", "completing", "needs_attention")):
        _fail("review_gate_state_invalid")
    _load_plan(row)
    return row["url"]
