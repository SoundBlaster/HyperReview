"""Optional head-revision check-run observations, outside model interpretation."""

from datetime import datetime, timezone
import re
import time

from . import intake, model_contract, render


SCHEMA = "hyperreview.ci-observations.v1"
MAX_CHECKS = 12
MAX_BYTES = 16384
_STATUSES = {"queued", "in_progress", "completed", "waiting", "pending", "requested"}
_CONCLUSIONS = {"success", "failure", "neutral", "cancelled", "skipped", "timed_out",
                "action_required", "stale", "startup_failure"}
_OMISSIONS = {"read_failed", "invalid_response", "invalid_check", "revision_mismatch",
              "page_limit", "check_limit"}
_FIELDS = {"schema", "repository", "head_sha", "retrieved_at", "checks", "omissions"}
_CHECK_FIELDS = {"id", "name", "status", "conclusion"}


def _valid_check(check):
    return (type(check) is dict and set(check) == _CHECK_FIELDS
            and type(check["id"]) is int and 0 < check["id"] < 2**63
            and type(check["name"]) is str and 1 <= len(check["name"]) <= 160
            and check["name"].isprintable()
            and model_contract._secret_reason(check["name"]) is None
            and type(check["status"]) is str and check["status"] in _STATUSES
            and (check["conclusion"] is None or
                 (type(check["conclusion"]) is str and check["conclusion"] in _CONCLUSIONS))
            and (check["status"] == "completed" or check["conclusion"] is None))


def validate(snapshot, repository, head_sha):
    """Validate the frozen optional suffix before binding it to a comment."""
    if (type(snapshot) is not dict or set(snapshot) != _FIELDS
            or snapshot["schema"] != SCHEMA or repository not in intake.ALLOWLIST
            or snapshot["repository"] != repository or snapshot["head_sha"] != head_sha
            or type(head_sha) is not str or not re.fullmatch(r"[0-9a-f]{40}", head_sha)
            or type(snapshot["retrieved_at"]) is not str
            or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", snapshot["retrieved_at"])
            or type(snapshot["checks"]) is not list or len(snapshot["checks"]) > MAX_CHECKS
            or not all(_valid_check(check) for check in snapshot["checks"])
            or len({check["id"] for check in snapshot["checks"]}) != len(snapshot["checks"])
            or type(snapshot["omissions"]) is not list
            or not all(type(code) is str and code in _OMISSIONS for code in snapshot["omissions"])
            or len(snapshot["omissions"]) != len(set(snapshot["omissions"]))
            or len(intake.encoded(snapshot)) > MAX_BYTES):
        raise ValueError("Invalid CI observations")
    datetime.strptime(snapshot["retrieved_at"], "%Y-%m-%dT%H:%M:%SZ")
    return snapshot


def collect(repository, head_sha, *, api=None):
    """One bounded read; CI failure, pending checks and read errors are data."""
    snapshot = {"schema": SCHEMA, "repository": repository, "head_sha": head_sha,
                "retrieved_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "checks": [], "omissions": []}
    validate(snapshot, repository, head_sha)
    if api is None:
        api = intake.GitHub()
        # Separate from the authorization client's budget: no waiting for CI.
        api.deadline = min(api.deadline, time.monotonic() + 5)
    try:
        response = api.get(f"repos/{repository}/commits/{head_sha}/check-runs?per_page=100",
                           "{total_count,check_runs:[.check_runs[]|{id,name,status,conclusion,head_sha}]}")
        if (type(response) is not dict or type(response.get("total_count")) is not int
                or type(response.get("check_runs")) is not list
                or len(response["check_runs"]) > 100
                or response["total_count"] < len(response["check_runs"])):
            snapshot["omissions"].append("invalid_response")
        else:
            seen = set()
            for raw in response["check_runs"]:
                if type(raw) is not dict:
                    snapshot["omissions"].append("invalid_check")
                    continue
                if raw.get("head_sha") != head_sha:
                    snapshot["omissions"].append("revision_mismatch")
                    continue
                check = {key: raw.get(key) for key in _CHECK_FIELDS}
                if not _valid_check(check) or check["id"] in seen:
                    snapshot["omissions"].append("invalid_check")
                    continue
                seen.add(check["id"])
                if len(snapshot["checks"]) == MAX_CHECKS:
                    snapshot["omissions"].append("check_limit")
                    continue
                snapshot["checks"].append(check)
            if response["total_count"] > len(response["check_runs"]):
                snapshot["omissions"].append("page_limit")
    except (intake.IntakeError, OSError, ValueError, TypeError, KeyError):
        snapshot["omissions"].append("read_failed")
    snapshot["omissions"] = list(dict.fromkeys(snapshot["omissions"]))
    # Encoded non-ASCII names can exhaust the budget; discard optional rows.
    while len(intake.encoded(snapshot)) > MAX_BYTES:
        snapshot["checks"].pop()
        if "check_limit" not in snapshot["omissions"]:
            snapshot["omissions"].append("check_limit")
    return validate(snapshot, repository, head_sha)


def render_suffix(snapshot, repository, head_sha, *, max_bytes):
    """Render only API-reported run status, never infer per-test coverage."""
    if snapshot is None:
        return ""
    validate(snapshot, repository, head_sha)
    lines = ["\n\n<details>\n<summary>CI · дополнительное evidence</summary>\n",
             f"\nСнимок для `{head_sha[:8]}` · {snapshot['retrieved_at']} (UTC).\n",
             "\nРезультат check-run не доказывает выполнение конкретного теста, "
             "полноту покрытия или соответствие архитектуре.\n"]
    if snapshot["checks"]:
        lines.extend(["\n| Проверка | Статус | Результат |\n", "|---|---|---|\n"])
        for check in snapshot["checks"]:
            url = f"https://github.com/{repository}/runs/{check['id']}"
            lines.append(f"| [{render._text(check['name'])}]({url}) | "
                         f"{check['status']} | {check['conclusion'] or '—'} |\n")
    else:
        lines.append("\nНаблюдения check-run не получены; это не результат проверки.\n")
    if snapshot["omissions"]:
        lines.append("\nСнимок неполный: " + ", ".join(snapshot["omissions"]) + ".\n")
    lines.append("\nОтсутствие, ожидание или сбой CI не блокируют архитектурный обзор.\n\n</details>\n")
    text = "".join(lines)
    # Optional evidence must never push a valid architectural comment over its limit.
    return text if len(text.encode("utf-8")) <= max_bytes else ""
