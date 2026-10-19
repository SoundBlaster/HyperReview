"""Render a local review aid without promoting model interpretations to facts."""

import html
import difflib
import re
from urllib.parse import quote

from . import intake, model_contract


COMPACT_RENDER_VERSION = "compact-v3"


def _text(value):
    value = html.escape(value, quote=True).replace("@", "&#64;")
    return re.sub(r"([\\`*_{}\[\]()#+.!|>~-])", r"\\\1", value)


def _fence(value, language="hc"):
    longest = max((len(match) for match in re.findall(r"`+", value)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}{language}\n{value.rstrip()}\n{fence}\n"


def _address_labels(result):
    entries = result["identity_map"]
    counts = {}
    for side in ("before", "after"):
        for entry in entries:
            role = entry.get(f"{side}_role")
            if role is not None:
                counts[(side, role)] = counts.get((side, role), 0) + 1
    labels = {}
    for entry in entries:
        role = entry.get("after_role") or entry.get("before_role")
        if role is None:
            labels[entry["architecture_id"]] = entry["architecture_id"]
            continue
        repeated = any(counts.get((side, entry.get(f"{side}_role")), 0) > 1
                       for side in ("before", "after") if entry.get(f"{side}_role") is not None)
        labels[entry["architecture_id"]] = (
            f"{role}#{entry['architecture_id'][1:]}" if repeated else role
        )
    return labels


def render_preview(request, result, receipt, semantic_diff, *, tracking_status="not_started"):
    """Inputs must come from the successful compiler boundary, never raw model output.

    Compiler validation establishes structure and reference integrity. It does
    not establish whether an architectural interpretation follows from code.
    """
    model_contract.validate_request(request)
    model_contract.validate_result(result, request)
    if tracking_status not in ("not_started", "tracking_pending", "confirmed"):
        raise model_contract.ContractError("Rendering tracking status is invalid")
    tracking_label = {"not_started": "Tracking has not been confirmed.",
                      "tracking_pending": "Tracking delivery is pending.",
                      "confirmed": "Metadata-only tracking delivery is confirmed."}[tracking_status]
    address_labels = _address_labels(result)
    if (receipt.get("stage") != "projections_validated"
            or receipt.get("request_digest") != request["request_digest"]
            or receipt.get("result_digest") != intake.digest(result)
            or not re.fullmatch(r"[0-9a-f]{64}", receipt.get("compiler_sha256", ""))
            or semantic_diff.get("version") != "hypercode.diff/v1"
            or type(semantic_diff.get("changes")) is not list):
        raise model_contract.ContractError("Rendering requires a bound validated compiler result")
    lines = [
        "# HyperReview — inferred architectural change\n",
        "These projections are model interpretations of selected source, not accepted "
        "architectural intent or proof of runtime behavior. Compiler checks establish "
        "Hypercode structure and reference integrity only.\n",
        f"Repository: `{request['repository']}` · PR #{request['pr']}\n",
        ("Mode: **historical read-only**; publication is disabled.\n"
         if request["intake_mode"] == "historical_read_only" else ""),
        f"Before (merge base): `{request['merge_base_sha']}`\n",
        f"After: `{request['head_sha']}`\n",
        f"Request: `{request['request_digest']}`\n",
        f"Compiler SHA256: `{receipt['compiler_sha256']}`\n",
        f"Scope: {len(request['sources'])} supplied source records; "
        f"{len(request['omissions'])} omissions. {tracking_label}\n",
        "## Model summary (inferred)\n", _text(result["summary"]) + "\n",
        "## Paired Hypercode projections\n", "### Before\n", _fence(result["before_hc"]),
        "### After\n", _fence(result["after_hc"]),
        "## Compiler-derived structural changes\n",
        f"{len(semantic_diff['changes'])} change records. Tree order is not execution order.\n",
    ]
    for change in semantic_diff["changes"]:
        lines.append(f"- {_text(change['kind'])}: {_text(change['node'])}\n")
    lines.extend(["\n## Inferred claims\n"])
    for claim in result["claims"]:
        lines.extend([f"### {_text(claim['id'])}\n", _text(claim["text"]) + "\n",
                      "Status: **inferred**\n", "Scope: " + _text(claim["scope"]) + "\n",
                      "Architecture addresses: " + ", ".join(
                          _text(address_labels[value]) for value in claim["architecture_ids"]) + "\n",
                      "Source references: " + ", ".join(_text(value) for value in claim["source_refs"]) + "\n"])
        for limitation in claim["limitations"]:
            lines.append("- Limitation: " + _text(limitation) + "\n")
        lines.append("\n")
    lines.append("## Revision-specific source ledger\n")
    for source in request["sources"]:
        url = (f"https://github.com/{request['repository']}/blob/{source['revision']}/"
               f"{quote(source['path'], safe='/')}#L{source['line_start']}-L{source['line_end']}")
        lines.append(f"- {_text(source['id'])}: {source['side']} "
                     f"[{_text(source['path'])}]({url}); SHA256 `{source['content_sha256']}`\n")
    lines.append("\n## Identity decisions (inferred)\n")
    for identity in result["identity_map"]:
        lines.append(f"- {_text(address_labels[identity['architecture_id']])}: {_text(identity['reason'])}. "
                     f"Before refs: {', '.join(_text(ref) for ref in identity['before_refs']) or 'none'}; "
                     f"after refs: {', '.join(_text(ref) for ref in identity['after_refs']) or 'none'}.\n")
    lines.append("\n## Limitations and omissions\n")
    for limitation in [*request["scope"], *request["limitations"], *result["limitations"]]:
        lines.append("- " + _text(limitation) + "\n")
    for omission in request["omissions"]:
        lines.append("- Omitted: " + _text(omission.get("path") or "undisclosed path")
                     + " (" + _text(omission["reason"]) + ").\n")
    lines.append("\nNo PR code was executed by this analysis. An absent reference or unchanged "
                 "projection does not establish unchanged behavior. Publication requires separate "
                 "authorization, revision checks, and confirmed tracking delivery.\n")
    return "\n".join(lines).encode("utf-8")


def render_compact_preview(request, result, receipt, semantic_diff, *, tracking_status="not_started"):
    """Render a small review aid from the same validated, revision-bound inputs."""
    render_preview(request, result, receipt, semantic_diff, tracking_status=tracking_status)
    before = result["before_hc"].splitlines() if result["before_hc"].strip() else []
    after = result["after_hc"].splitlines() if result["after_hc"].strip() else []
    change = "\n".join(difflib.unified_diff(before, after, fromfile="before.hc",
                                           tofile="after.hc", lineterm=""))
    lines = ["# HyperReview — архитектурный эскиз изменения\n",
             ("**Исторический разбор, только локально; публикация отключена.**\n\n"
              if request["intake_mode"] == "historical_read_only" else ""),
             _text(result["summary"]) + "\n",
             "Интерпретация выбранных исходников; порядок узлов не означает порядок выполнения.\n",
             (_fence(change, "diff") if change else
              "Структурных изменений в проекции нет. Текущая проекция:\n"
              + _fence(result["after_hc"]))]
    sources = {source["id"]: source for source in request["sources"]}
    address_labels = _address_labels(result)
    for identity in result["identity_map"]:
        links = []
        refs = list(dict.fromkeys(identity["after_refs"] + identity["before_refs"]))
        for ref in refs:
            source = sources[ref]
            url = (f"https://github.com/{request['repository']}/blob/{source['revision']}/"
                   f"{quote(source['path'], safe='/')}#L{source['line_start']}-L{source['line_end']}")
            links.append(f"[{_text(source['path'])}]({url})")
        lines.append(f"- `{address_labels[identity['architecture_id']]}` — {_text(identity['reason'])} "
                     + "; ".join(links) + "\n")
    lines.extend(["\n<details>\n<summary>Границы анализа и основания</summary>\n",
                  f"PR #{request['pr']}: `{request['merge_base_sha']}` → `{request['head_sha']}`.\n",
                  f"Исходников в анализе: {len(request['sources'])}; пропущено: {len(request['omissions'])}.\n",
                  "Компилятор проверил структуру Hypercode и ссылки. Соответствие интерпретации коду "
                  "и поведение программы этим не доказаны.\n"])
    for limitation in [*request["scope"], *request["limitations"], *result["limitations"]]:
        lines.append("- " + _text(limitation) + "\n")
    lines.extend(["\n</details>\n", "**Ок или не ок?**\n"])
    return "\n".join(lines).encode("utf-8")
