"""Read-only GitHub publication planning for a bound private preview."""

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
import stat

from . import intake, render, tracking
from .feedback import (FeedbackError, _MAX_PREVIEW_BYTES, _parse_json_bytes,
                       _read_bounded_regular, _safe_bundle)
from .model_contract import ContractError
from .storage import StorageError, read_json, write_bundle


COMMENT_MARKER = "<!-- hyperreview:comment:v1 -->"
PLAN_SCHEMA = "hyperreview.publication-plan.v1"
MAX_COMMENT_BYTES = 65536
MAX_COMMENT_PAGES = 10
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_HEX40 = re.compile(r"[0-9a-f]{40}\Z")


class PublicationError(Exception):
    """Raised when local publication inputs are invalid or tampered."""


class _CommentInventoryError(Exception):
    pass


def _require(condition):
    if not condition:
        raise PublicationError("Publication input or preview bundle is invalid")


def _safe_output_root(path, bundle):
    try:
        root = Path(path)
    except (TypeError, ValueError):
        raise PublicationError("Publication input or preview bundle is invalid") from None
    _require(root.is_absolute() and ".." not in root.parts
             and root != bundle and bundle not in root.parents)
    for parent in (*reversed(root.parents), root):
        _require(not parent.is_symlink())
    if root.exists():
        _require(root.is_dir() and stat.S_IMODE(root.stat().st_mode) & 0o077 == 0)
    return root


def _read_local_preview(bundle, expected_preview_sha256):
    _require(type(expected_preview_sha256) is str
             and _HEX64.fullmatch(expected_preview_sha256) is not None)
    try:
        event = tracking.build_event(bundle)
        request = read_json(bundle / "request.json", max_bytes=262144)
        result = read_json(bundle / "result.json", max_bytes=1024 * 1024)
        compiler = read_json(bundle / "compiler-receipt.json", max_bytes=262144)
        raw_diff = _read_bounded_regular(bundle / "diff.json", 1024 * 1024)
        diff = _parse_json_bytes(raw_diff)
        raw_preview = _read_bounded_regular(bundle / "preview-compact.md", _MAX_PREVIEW_BYTES)
        result_digest = intake.digest(result)
        _require(type(request) is dict and type(result) is dict
                 and type(compiler) is dict and type(diff) is dict
                 and hashlib.sha256(raw_diff).hexdigest() == compiler.get("diff_sha256")
                 and event["metadata"]["request_digest"] == request.get("request_digest")
                 and event["metadata"]["result_digest"] == result_digest
                 and compiler.get("request_digest") == request.get("request_digest")
                 and compiler.get("result_digest") == result_digest
                 and compiler.get("compiler_sha256") == event["metadata"]["compiler_sha256"]
                 and raw_preview == render.render_compact_preview(request, result, compiler, diff))
        preview_sha256 = hashlib.sha256(raw_preview).hexdigest()
        _require(preview_sha256 == expected_preview_sha256)
        return event, request, result, raw_preview, preview_sha256
    except PublicationError:
        raise
    except (FeedbackError, tracking.TrackingError, StorageError, ContractError,
            OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError):
        raise PublicationError("Publication could not be bound to a validated preview") from None


def _tracking_state(bundle, event):
    receipt_path = bundle / "tracking-receipt.json"
    metadata = read_json(bundle / "metadata.json", max_bytes=tracking.MAX_EVENT_BYTES)
    _require(metadata.get("tracking_correlation_id") == event["correlation_id"]
             and metadata.get("request_digest") == event["metadata"]["request_digest"]
             and metadata.get("result_digest") == event["metadata"]["result_digest"])
    if not receipt_path.exists():
        return "tracking_unconfirmed", None
    try:
        receipt_raw = _read_bounded_regular(receipt_path, tracking.MAX_EVENT_BYTES)
        receipt = _parse_json_bytes(receipt_raw)
    except (FeedbackError, OSError, ValueError, StorageError):
        raise PublicationError("Publication could not be bound to a validated preview") from None
    if type(receipt) is dict and receipt.get("tracking_status") == "pending":
        expected_keys = {"schema", "correlation_id", "attempt", "tracking_status",
                         "experiment_id", "run_id", "trace_id", "event_digest", "failure_code"}
        _require(set(receipt) == expected_keys
                 and receipt.get("schema") == "hyperreview.tracking-receipt.v1"
                 and receipt.get("correlation_id") == event["correlation_id"]
                 and receipt.get("attempt") == event["attempt"]
                 and all(receipt.get(key) is None for key in
                         ("experiment_id", "run_id", "trace_id", "event_digest"))
                 and type(receipt.get("failure_code")) is str)
        return "tracking_unconfirmed", None
    try:
        tracking._validate_receipt(receipt, event)
    except tracking.TrackingError:
        raise PublicationError("Publication could not be bound to a validated preview") from None
    return "confirmed", receipt


def _revision(value):
    return type(value) is str and _HEX40.fullmatch(value) is not None


def _blockers_for_eligibility(repo, number, pr, account):
    blockers = []
    if repo not in intake.ALLOWLIST or number <= 0:
        blockers.append("repository_or_pr_not_allowlisted")
    if account != intake.AUTHOR:
        blockers.append("authenticated_account_mismatch")
    if pr.get("author") != intake.AUTHOR:
        blockers.append("pr_author_mismatch")
    if pr.get("state") != "open":
        blockers.append("pr_not_open")
    if pr.get("draft") is not False:
        blockers.append("pr_is_draft")
    if pr.get("base_repo") != repo or pr.get("head_repo") != repo:
        blockers.append("cross_repository_pr")
    if pr.get("number") != number:
        blockers.append("pr_identity_mismatch")
    return blockers


def _eligibility_blockers(repo, number, pr, account):
    blockers = _blockers_for_eligibility(repo, number, pr, account)
    try:
        intake.eligible(repo, number, pr, account)
    except intake.IntakeError:
        if not blockers:
            blockers.append("pr_ineligible")
    return blockers


def _comments(api, repo, number, account):
    all_comments = []
    for page in range(1, MAX_COMMENT_PAGES + 1):
        try:
            response = api.get(
                f"repos/{repo}/issues/{number}/comments?per_page=100&page={page}",
                "[.[]|{id,user:.user.login,body}]",
            )
        except Exception:
            raise _CommentInventoryError from None
        if type(response) is not list or len(response) > 100:
            raise _CommentInventoryError
        if any(type(item) is not dict or type(item.get("id")) is not int
               or item["id"] <= 0 or type(item.get("user")) is not str
               or type(item.get("body")) is not str for item in response):
            raise _CommentInventoryError
        all_comments.extend(response)
        if len(response) < 100:
            return all_comments
    raise _CommentInventoryError


def _comment_action(comments, account, body):
    marked = [item for item in comments
              if type(item) is dict and type(item.get("user")) is str
              and item["user"] == account and type(item.get("body")) is str
              and COMMENT_MARKER in item["body"]]
    if len(marked) > 1:
        return None, None, "duplicate_own_marker_comments"
    if not marked:
        return "create", None, None
    comment = marked[0]
    if comment["body"] == body:
        return "unchanged", comment["id"], None
    return "update", comment["id"], None


def _api_get(api, endpoint, query):
    try:
        return api.get(endpoint, query)
    except intake.IntakeError:
        raise
    except Exception:
        raise intake.IntakeError("GitHub read failed") from None


def plan_publication(bundle, *, expected_preview_sha256, output_root, api=None):
    """Persist a private dry-run plan; this function never writes to GitHub."""
    try:
        bundle = _safe_bundle(bundle)
        root = _safe_output_root(output_root, bundle)
        event, request, result, preview, preview_sha256 = _read_local_preview(
            bundle, expected_preview_sha256)
        tracking_status, tracking_receipt = _tracking_state(bundle, event)
    except PublicationError:
        raise
    except (FeedbackError, OSError, ValueError, TypeError):
        raise PublicationError("Publication input or preview bundle is invalid") from None

    try:
        evidence = read_json(bundle / "evidence.json", max_bytes=262144)
    except (OSError, ValueError, TypeError, StorageError):
        raise PublicationError("Publication could not be bound to a validated preview") from None
    _require(type(evidence) is dict
             and intake.digest({key: value for key, value in evidence.items()
                                if key != "evidence_digest"})
             == event["metadata"]["evidence_digest"]
             and evidence.get("repository") == request["repository"]
             and evidence.get("pr") == request["pr"])
    pinned = {field: evidence.get(field) for field in ("base_sha", "head_sha", "merge_base_sha")}
    repo, number = request["repository"], request["pr"]
    if repo not in intake.ALLOWLIST or type(number) is not int or number <= 0:
        raise PublicationError("Publication input or preview bundle is invalid")
    api = api or intake.GitHub()
    blockers = []
    account = None
    initial = None
    current = {"base_sha": None, "head_sha": None, "merge_base_sha": None}
    comments = []
    try:
        account = _api_get(api, "user", "{login}")["login"]
        initial = intake.metadata(api, repo, number)
        blockers.extend(_eligibility_blockers(repo, number, initial, account))
        if all(_revision(initial.get(field)) for field in ("base_sha", "head_sha")):
            current["base_sha"] = initial["base_sha"]
            current["head_sha"] = initial["head_sha"]
            compare = _api_get(
                api, f"repos/{repo}/compare/{initial['base_sha']}...{initial['head_sha']}",
                "{merge_base_sha:.merge_base_commit.sha}",
            )
            current["merge_base_sha"] = compare.get("merge_base_sha")
        else:
            blockers.append("live_revision_invalid")
        try:
            comments = _comments(api, repo, number, account)
        except _CommentInventoryError:
            blockers.append("comment_inventory_incomplete")
    except (intake.IntakeError, KeyError, TypeError, AttributeError):
        blockers.append("github_read_failed")

    if not _revision(current["base_sha"]) or current["base_sha"] != pinned["base_sha"]:
        blockers.append("base_revision_changed")
    if not _revision(current["head_sha"]) or current["head_sha"] != pinned["head_sha"]:
        blockers.append("head_revision_changed")
    if not _revision(current["merge_base_sha"]) or current["merge_base_sha"] != pinned["merge_base_sha"]:
        blockers.append("merge_base_changed")
    if tracking_status != "confirmed":
        blockers.append("tracking_unconfirmed")

    body = (COMMENT_MARKER + "\n\n" + preview.decode("utf-8", errors="strict"))
    if len(body.encode("utf-8")) > MAX_COMMENT_BYTES:
        raise PublicationError("Publication comment exceeds the GitHub body limit")
    action, comment_id, comment_blocker = _comment_action(comments, account, body)
    if comment_blocker:
        blockers.append(comment_blocker)

    final_account = None
    final_pr = None
    final_current = dict(current)
    try:
        final_account = _api_get(api, "user", "{login}")["login"]
        final_pr = intake.metadata(api, repo, number)
        final_current = {"base_sha": final_pr.get("base_sha"),
                         "head_sha": final_pr.get("head_sha"),
                         "merge_base_sha": (current["merge_base_sha"]
                                            if final_pr.get("base_sha") == current["base_sha"]
                                            and final_pr.get("head_sha") == current["head_sha"]
                                            else None)}
        if final_account != account:
            blockers.append("authenticated_account_changed")
        for field, code in (("base_sha", "base_revision_changed"),
                            ("head_sha", "head_revision_changed")):
            if final_pr.get(field) != current[field]:
                blockers.append(code)
        blockers.extend(_eligibility_blockers(repo, number, final_pr, final_account))
    except (intake.IntakeError, KeyError, TypeError, AttributeError):
        blockers.append("final_recheck_failed")

    # Stable order and no duplicate codes, even when the final recheck finds a
    # second reason for the same revision blocker.
    blockers = list(dict.fromkeys(blockers))
    status = "blocked" if blockers else "ready"
    if status == "blocked":
        action, comment_id = None, None
    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    event_metadata = event["metadata"]
    plan = {
        "schema": PLAN_SCHEMA,
        "mode": "dry_run",
        "status": status,
        "blockers": blockers,
        "action": action,
        "comment_id": comment_id,
        "repository": repo,
        "pr": number,
        "base_sha": pinned["base_sha"],
        "head_sha": pinned["head_sha"],
        "merge_base_sha": pinned["merge_base_sha"],
        "current_base_sha": final_current["base_sha"],
        "current_head_sha": final_current["head_sha"],
        "current_merge_base_sha": final_current["merge_base_sha"],
        "request_digest": event_metadata["request_digest"],
        "result_digest": event_metadata["result_digest"],
        "preview_sha256": preview_sha256,
        "tracking_status": tracking_status,
        "tracking_correlation_id": event["correlation_id"],
        "tracking_experiment_id": tracking_receipt["experiment_id"] if tracking_receipt else None,
        "tracking_run_id": tracking_receipt["run_id"] if tracking_receipt else None,
        "tracking_trace_id": tracking_receipt["trace_id"] if tracking_receipt else None,
        "checked_at": checked_at,
        "authorization_required": True,
        "writes_performed": False,
    }
    try:
        destination = write_bundle(
            {"plan.json": intake.encoded(plan), "comment.md": body.encode("utf-8")}, root)
    except (StorageError, OSError, ValueError, TypeError):
        raise PublicationError("Publication plan could not be saved privately") from None
    return destination, plan
