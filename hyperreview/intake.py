"""Read-only GitHub intake. Source remains data, never executable instructions."""

import base64
import hashlib
import html
import json
import os
from pathlib import Path, PurePosixPath
import re
import selectors
import subprocess
import time
from datetime import datetime, timezone
from urllib.parse import quote
from uuid import uuid4

from . import __version__
from .pr_eligibility import PullRequestEligibilityContext, PullRequestMetadataEligibility


ALLOWLIST = frozenset(("0al-spec/SpecGraph", "0al-spec/Hypercode"))
AUTHOR = "SoundBlaster"
MAX_FILES = 30
MAX_BYTES = 262144
DEADLINE_SECONDS = 300
API_BYTES = 4 * 1024 * 1024
SCHEMA = "hyperreview.evidence.v1"
POLICY = "own-pr-intake.v1"
EXTENSIONS = frozenset((".py", ".swift", ".rs", ".ts", ".tsx", ".js", ".jsx",
                        ".c", ".h", ".cpp", ".hpp", ".m", ".mm", ".md", ".hc"))
OPERATOR_FILES = frozenset(("agents.md", "claude.md", "skill.md", "mcp.json"))


class IntakeError(Exception):
    pass


def encoded(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class GitHub:
    def __init__(self):
        self.deadline = time.monotonic() + DEADLINE_SECONDS

    def get(self, endpoint, query="."):
        # Fixed executable, argv and github.com host; no shell or PR checkout.
        if time.monotonic() >= self.deadline:
            raise IntakeError("GitHub read deadline exceeded")
        command = ["gh", "api", "--hostname", "github.com", endpoint, "--jq", query]
        try:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError as error:
            raise IntakeError("GitHub CLI is unavailable") from error
        streams = selectors.DefaultSelector()
        output = bytearray()
        size = 0
        call_deadline = min(self.deadline, time.monotonic() + 60)
        try:
            for pipe in (process.stdout, process.stderr):
                os.set_blocking(pipe.fileno(), False)
                streams.register(pipe, selectors.EVENT_READ)
            while streams.get_map():
                remaining = call_deadline - time.monotonic()
                if remaining <= 0:
                    raise IntakeError("GitHub read deadline exceeded")
                for key, _ in streams.select(timeout=min(remaining, 1)):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        streams.unregister(key.fileobj)
                        continue
                    size += len(chunk)
                    if size > API_BYTES:
                        raise IntakeError("GitHub response exceeded the intake limit")
                    if key.fileobj is process.stdout:
                        output.extend(chunk)
            remaining = call_deadline - time.monotonic()
            if remaining <= 0:
                raise IntakeError("GitHub read deadline exceeded")
            if process.wait(timeout=remaining) != 0:
                raise IntakeError("GitHub read failed; verify authentication and repository access")
            return json.loads(output)
        except (ValueError, subprocess.TimeoutExpired) as error:
            raise IntakeError("GitHub returned invalid data or exceeded the deadline") from error
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
            streams.close()
            process.stdout.close()
            process.stderr.close()


def metadata(api, repo, number):
    return api.get(
        f"repos/{repo}/pulls/{number}",
        "{number,state,draft,author:.user.login,base_repo:.base.repo.full_name,"
        "head_repo:.head.repo.full_name,base_sha:.base.sha,head_sha:.head.sha}",
    )


def eligible(repo, number, pr, account):
    if repo not in ALLOWLIST or number <= 0:
        raise IntakeError("Repository or PR is outside the initial operator policy")
    if account != AUTHOR:
        raise IntakeError("Authenticated GitHub account differs from the configured author")
    context = PullRequestEligibilityContext(
        requested_number=number,
        requested_repository=repo,
        configured_author=AUTHOR,
        number=pr.get("number"),
        author=pr.get("author"),
        state=pr.get("state"),
        draft=pr.get("draft"),
        base_repository=pr.get("base_repo"),
        head_repository=pr.get("head_repo"),
    )
    if not PullRequestMetadataEligibility().is_satisfied_by(context):
        raise IntakeError("PR is ineligible: require configured author, same repository, open and non-draft")
    for name in ("base_sha", "head_sha"):
        if not re.fullmatch(r"[0-9a-f]{40}", pr.get(name, "")):
            raise IntakeError("PR has an invalid revision identity")


def exclusion(path):
    if not isinstance(path, str) or not path or any(ord(c) < 32 or ord(c) == 127 for c in path):
        return "invalid_path"
    parts = path.split("/")
    if path.startswith("/") or any(part in ("", ".", "..") for part in parts):
        return "invalid_path"
    lowered = [part.lower() for part in parts]
    name = lowered[-1]
    if (name in OPERATOR_FILES or any(part in (".codex", ".agents", ".claude", ".ssh", ".aws")
                                      for part in lowered)):
        return "operator_file"
    if (any(part.startswith(".env") or re.search(r"secret|credential|password|token", part)
            for part in lowered) or PurePosixPath(name).suffix in (".pem", ".key", ".p12", ".pfx")):
        return "sensitive_path"
    if PurePosixPath(name).suffix not in EXTENSIONS:
        return "unsupported_format"
    return None


def tree(api, repo, sha):
    response = api.get(f"repos/{repo}/git/trees/{sha}?recursive=1")
    if response.get("truncated") is not False:
        raise IntakeError("GitHub tree inventory is incomplete; intake stopped")
    return {entry["path"]: entry for entry in response["tree"]}


def source(api, repo, revision, path, entries, budget):
    entry = entries.get(path)
    if entry is None:
        return None, "missing_tree_entry"
    if entry.get("type") != "blob" or entry.get("mode") not in ("100644", "100755"):
        return None, "symlink_or_nonregular"
    size = entry.get("size")
    if not isinstance(size, int) or size < 0 or size > budget:
        return None, "input_byte_limit"
    try:
        blob = api.get(f"repos/{repo}/git/blobs/{entry['sha']}")
        if blob.get("encoding") != "base64":
            return None, "unsupported_blob_encoding"
        raw = base64.b64decode("".join(blob["content"].split()), validate=True)
        # Verify the Git object as well as recording a content SHA-256.
        object_sha = hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()
        if len(raw) != size or object_sha != entry["sha"]:
            return None, "blob_integrity_failure"
        if b"\0" in raw:
            return None, "binary_content"
        text = raw.decode("utf-8")
    except IntakeError:
        return None, "source_read_failure"
    except (ValueError, KeyError, UnicodeError):
        return None, "invalid_or_non_utf8_blob"
    return {
        "revision": revision, "path": path, "git_blob_sha": entry["sha"],
        "content_sha256": hashlib.sha256(raw).hexdigest(), "content_bytes": len(raw),
        "line_start": 1 if text else None,
        "line_end": raw.count(b"\n") + int(not raw.endswith(b"\n")) if raw else None,
        "content": text, "trust": "untrusted_source_data",
        "url": f"https://github.com/{repo}/blob/{revision}/{quote(path, safe='/')}",
    }, None


def collect(repo, number, api=None):
    if repo not in ALLOWLIST or number <= 0:
        raise IntakeError("Repository or PR is outside the initial operator policy")
    api = api or GitHub()
    account = api.get("user", "{login}")["login"]
    pr = metadata(api, repo, number)
    eligible(repo, number, pr, account)
    compare = api.get(
        f"repos/{repo}/compare/{pr['base_sha']}...{pr['head_sha']}",
        "{merge_base_sha:.merge_base_commit.sha,files:[.files[]|{filename,previous_filename,status}]}",
    )
    merge_base = compare["merge_base_sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", merge_base):
        raise IntakeError("Comparison has an invalid merge-base identity")
    files = compare["files"]
    before_tree = tree(api, repo, merge_base)
    after_tree = tree(api, repo, pr["head_sha"])
    # Derive complete changed-path inventory from pinned trees, avoiding the
    # compare API's 300-file cap. Rename hints may be incomplete at that cap.
    hints = {f["filename"]: f for f in files}
    changed = sorted(path for path in before_tree.keys() | after_tree.keys()
                     if before_tree.get(path) != after_tree.get(path)
                     and any(entries.get(path, {}).get("type") in ("blob", "commit")
                             for entries in (before_tree, after_tree)))
    renamed_from = {f["previous_filename"] for f in files
                    if f["status"] == "renamed" and f.get("previous_filename")}
    inventory = []
    for path in changed:
        if path in renamed_from and path not in after_tree:
            continue
        hint = hints.get(path, {})
        old_path = hint.get("previous_filename") if hint.get("status") == "renamed" else path
        if old_path not in before_tree:
            old_path = None
        new_path = path if path in after_tree else None
        inventory.append({"before_path": old_path, "after_path": new_path,
                          "status": "renamed" if old_path and old_path != path else
                          "modified" if old_path and new_path else "added" if new_path else "removed",
                          "sources": [], "omissions": []})
    pack = {
        "schema": SCHEMA, "policy": POLICY, "collector_version": __version__,
        "stage": "evidence_collected",
        "delivery_mode": "preview", "repository": repo, "pr": number,
        "authenticated_account": account, **pr, "merge_base_sha": merge_base,
        "collected_at": utc_now(), "correlation_id": str(uuid4()),
        # Account for final metadata before selecting source/check records.
        # Fixed-width placeholders are replaced without growing the JSON pack.
        "rechecked_at": utc_now(), "evidence_digest": "0" * 64,
        "tracking_status": "not_started", "files": inventory,
        "scope": {"inventory": "complete_pinned_tree_comparison",
                  "source": "whole_selected_changed_files_only",
                  "rename_hints": "possibly_incomplete" if len(files) >= 300 else "compare_api",
                  "surrounding_files": "not_collected", "pr_authored_text": "not_collected",
                  "behavior": "not_executed", "secret_detection": "path_filter_only_not_a_content_guarantee",
                  "commit_status_contexts": "not_collected"},
        "limits": {"source_files": MAX_FILES, "evidence_bytes": MAX_BYTES,
                   "deadline_seconds": DEADLINE_SECONDS},
        "checks": [], "check_omissions": [],
    }
    if len(encoded(pack)) + 128 > MAX_BYTES:
        raise IntakeError("Changed-file inventory exceeds the evidence limit")
    selected = 0
    for item in inventory:
        paths = [p for p in (item["before_path"], item["after_path"]) if p is not None]
        reason = next((exclusion(p) for p in paths if exclusion(p)), None)
        if reason or selected >= MAX_FILES:
            item["omissions"].append({"side": "both", "reason": reason or "source_file_limit"})
            continue
        included = False
        for side, revision, entries in (("before", merge_base, before_tree),
                                        ("after", pr["head_sha"], after_tree)):
            path = item[f"{side}_path"]
            if path is None:
                continue  # Expected absence for an addition/removal, not a read failure.
            budget = MAX_BYTES - len(encoded(pack)) - 1024
            record, reason = source(api, repo, revision, path, entries, max(0, budget))
            if record is not None:
                record["side"] = side
                item["sources"].append(record)
                if len(encoded(pack)) + 1024 > MAX_BYTES:
                    item["sources"].pop()
                    reason = "encoded_evidence_byte_limit"
                else:
                    included = True
            if reason:
                item["omissions"].append({"side": side, "reason": reason})
        if included:
            selected += 1
    try:
        checks = api.get(f"repos/{repo}/commits/{pr['head_sha']}/check-runs?per_page=100",
                         "{total_count,check_runs:[.check_runs[]|{id,name,status,conclusion,head_sha}]}")
        observed_at = utc_now()
        for check in checks["check_runs"]:
            if check.get("head_sha") != pr["head_sha"]:
                pack["check_omissions"].append("revision_mismatch")
                continue
            record = {**check, "retrieved_at": observed_at, "method": "github_check_runs_api"}
            pack["checks"].append(record)
            if len(encoded(pack)) + 128 > MAX_BYTES:
                pack["checks"].pop()
                pack["check_omissions"].append("evidence_byte_limit")
                break
        if checks["total_count"] > len(checks["check_runs"]):
            pack["check_omissions"].append("check_api_page_limit")
    except IntakeError:
        pack["check_omissions"].append("check_read_failure")
    current = metadata(api, repo, number)
    eligible(repo, number, current, account)
    if any(current[field] != pr[field] for field in ("base_sha", "head_sha")):
        raise IntakeError("PR revisions changed during collection; rerun intake")
    pack["rechecked_at"] = utc_now()
    pack["evidence_digest"] = digest({key: value for key, value in pack.items()
                                      if key != "evidence_digest"})
    if len(encoded(pack)) > MAX_BYTES:
        raise IntakeError("Evidence pack exceeds the byte limit")
    return pack


def preview(pack):
    rows = ["# HyperReview evidence preview", "", "Stage: **evidence_collected**.", "",
            "Architecture inference, Hypercode projections, and MLflow tracking have not started.", "",
            f"PR: https://github.com/{pack['repository']}/pull/{pack['pr']}", "",
            f"Base: `{pack['base_sha']}`", f"Merge base: `{pack['merge_base_sha']}`",
            f"Head: `{pack['head_sha']}`", f"Evidence digest: `{pack['evidence_digest']}`", "",
            "Source scope: selected changed files only. No program was executed.",
            "Path filtering does not guarantee that source content contains no secrets.", "",
            "## Changed-file inventory", "", "```text"]
    for item in pack["files"]:
        path = item["after_path"] or item["before_path"]
        reasons = ", ".join(o["reason"] for o in item["omissions"]) or "none"
        # JSON encoding keeps control characters/backticks from closing the fence.
        rows.append(json.dumps({"path": path, "status": item["status"],
                                "included_sides": len(item["sources"]), "omissions": reasons}))
    rows += ["```", "", f"Check-run observations: {len(pack['checks'])} (head revision only).",
             "Commit-status contexts and surrounding files were not collected.",
             f"Check omissions: {html.escape(', '.join(pack['check_omissions']) or 'none')}.",
             "", "A passing check establishes only its own reported result."]
    return "\n".join(rows) + "\n"


def save(pack, root):
    # Operator chooses the destination. No path from source/model data is used.
    root = Path(os.path.abspath(root))
    for parent in (*reversed(root.parents), root):
        if parent.is_symlink():
            raise IntakeError("Output root must not traverse symlinks")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination = root / str(uuid4())
    destination.mkdir(mode=0o700)
    try:
        for name, body in (("evidence.json", encoded(pack)), ("preview.md", preview(pack).encode())):
            fd = os.open(destination / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as file:
                file.write(body)
    except Exception:
        for name in ("evidence.json", "preview.md"):
            (destination / name).unlink(missing_ok=True)
        destination.rmdir()
        raise
    return destination
