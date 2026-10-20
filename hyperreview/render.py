"""Render a local review aid without promoting model interpretations to facts."""

import html
import difflib
import re
from urllib.parse import quote

from . import intake, model_contract, relation_sheet, source_analysis


COMPACT_RENDER_VERSION = "compact-v8"
_SMALL_PROJECTION_LINES = 40


def _containment_keys(lines):
    """Qualify generated node lines by their indentation-based ancestry.

    These keys only control presentation matching. They do not establish
    cross-revision identity or replace the compiler's IR comparison.
    """
    stack = []
    occurrences = {}
    keys = []
    for line in lines:
        if not line.strip():
            keys.append(((), line))
            continue
        indent = len(line) - len(line.lstrip())
        while stack and stack[-1][0] >= indent:
            stack.pop()
        parent = tuple(item[1] for item in stack)
        label = line.strip()
        sibling = (parent, label)
        occurrence = occurrences.get(sibling, 0)
        occurrences[sibling] = occurrence + 1
        address = (label, occurrence)
        keys.append((parent + (address,), line))
        stack.append((indent, address))
    return keys


def _diff_range(start, stop):
    length = stop - start
    if length == 1:
        return str(start + 1)
    return f"{start if length == 0 else start + 1},{length}"


def _composition_diff(before, after, context):
    """Emit a valid unified patch that also exposes changed containing paths."""
    matcher = difflib.SequenceMatcher(None, _containment_keys(before),
                                     _containment_keys(after), autojunk=False)
    lines = []
    for group in matcher.get_grouped_opcodes(context):
        if not lines:
            lines.extend(["--- before.hc", "+++ after.hc"])
        first, last = group[0], group[-1]
        lines.append(f"@@ -{_diff_range(first[1], last[2])} "
                     f"+{_diff_range(first[3], last[4])} @@")
        for tag, before_start, before_stop, after_start, after_stop in group:
            if tag == "equal":
                lines.extend(" " + line for line in before[before_start:before_stop])
            if tag in ("delete", "replace"):
                lines.extend("-" + line for line in before[before_start:before_stop])
            if tag in ("insert", "replace"):
                lines.extend("+" + line for line in after[after_start:after_stop])
    return "\n".join(lines)


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


def _relation_table(request, result):
    """Render the bounded explanation extension from canonical inferred claims."""
    claims = [claim for claim in result["claims"] if claim["id"].startswith("relation-")]
    if not claims:
        return []
    sources = {source["id"]: source for source in request["sources"]}
    lines = ["\n## Связи и основания\n",
             "Связи описаны отдельно от вложенности `.hc`; основания — в правой колонке.\n",
             "| Связь | Что видно в источниках | Основания |",
             "| --- | --- | --- |"]
    for claim in claims[:6]:
        groups = {}
        for ref in claim["source_refs"]:
            source = sources[ref]
            spans = source_analysis.citation_spans(source, claim["text"] + " " + claim["scope"])
            locations = groups.setdefault(source["path"], {})
            if spans:
                for span in spans:
                    narrowed = {**source, "line_start": span["line_start"], "line_end": span["line_end"]}
                    url = _source_url(request, narrowed, lines=True)
                    locations[url] = (f"[{_text(span['label'])} L{span['line_start']}–{span['line_end']}]"
                                      f"({url})")
            else:
                url = _source_url(request, source, lines=True)
                locations[url] = f"[L{source['line_start']}–{source['line_end']}]({url})"
        links = [_text(path.rsplit("/", 1)[-1]) + ": " + ", ".join(locations.values())
                 for path, locations in groups.items()]
        # Newlines would split Markdown table rows; escape every model field
        # through the same text boundary as ordinary explanations.
        text = _text(" ".join(claim["text"].split()))
        scope = _text(" ".join(claim["scope"].split()))
        lines.append(f"| {text} | {scope} | {'; '.join(links)} |")
    lines.append("")
    return lines


def _companion_view(receipt):
    sheets = receipt.get("relationship_sheets", {})
    if not sheets:
        return []
    lines = ["\n<details>\n<summary>Связи в Hypercode (.hcs)</summary>\n"]
    for side in ("before", "after"):
        if side in sheets:
            lines.extend([f"### {side}.hcs\n", _fence(sheets[side]["content"], "hcs")])
    lines.append("</details>\n")
    return lines


def _configuration_coverage(request):
    lines = []
    for coverage in request.get("configuration_coverage", []):
        omissions = coverage["omissions"]
        ranges = "; ".join(f"L{item['line_start']}–{item['line_end']}: {item['reason']}"
                           for item in omissions[:8])
        extra = f"; ещё {len(omissions) - 8} диапазонов" if len(omissions) > 8 else ""
        lines.append("- Конфигурация: " + _text(coverage["path"]) + "; "
                     + _text(coverage["side"]) + "; охват " + _text(coverage["coverage"])
                     + f"; фрагментов {len(coverage['source_ids'])}. "
                     + _text(ranges + extra) + "\n")
    return lines


def _source_groups(refs, sources):
    groups = {}
    for ref in dict.fromkeys(refs):
        source = sources[ref]
        groups.setdefault(source["path"], {}).setdefault(source["side"], []).append(source)
    return groups


def _source_url(request, source, *, lines=False):
    url = (f"https://github.com/{request['repository']}/blob/{source['revision']}/"
           f"{quote(source['path'], safe='/')}")
    if lines:
        url += f"#L{source['line_start']}-L{source['line_end']}"
    return url


def _compact_source_links(request, groups):
    links = []
    for path, sides in groups.items():
        versions = [f"[{'до' if side == 'before' else 'после'}]"
                    f"({_source_url(request, sides[side][0])})"
                    for side in ("before", "after") if side in sides]
        links.append(_text(path) + " — " + " / ".join(versions))
    return "; ".join(links)


def _identity_source_ranges(request, result, sources, labels):
    """Keep exact per-node evidence ranges available outside the main prose."""
    lines = ["\n### Точные диапазоны источников по узлам\n"]
    for identity in result["identity_map"]:
        lines.append("\n**" + _text(labels[identity["architecture_id"]]) + "**\n")
        groups = _source_groups(identity["before_refs"] + identity["after_refs"], sources)
        for path, sides in groups.items():
            versions = []
            for side in ("before", "after"):
                if side not in sides:
                    continue
                refs = sorted(sides[side], key=lambda source: (source["line_start"], source["line_end"]))
                ranges = [f"[L{source['line_start']}–{source['line_end']}]"
                          f"({_source_url(request, source, lines=True)})" for source in refs]
                versions.append(("до: " if side == "before" else "после: ") + ", ".join(ranges))
            lines.append("- " + _text(path) + " — " + "; ".join(versions) + "\n")
    return lines


def render_preview(request, result, receipt, semantic_diff, *, tracking_status="not_started"):
    """Inputs must come from the successful compiler boundary, never raw model output.

    Compiler validation establishes structure and reference integrity. It does
    not establish whether an architectural interpretation follows from code.
    """
    model_contract.validate_request(request)
    model_contract.validate_result(result, request)
    try:
        sheets = relation_sheet.build(request, result)
    except ValueError as error:
        raise model_contract.ContractError("Rendering relationship sheets are invalid") from error
    if sheets or receipt.get("relationship_sheets"):
        if (receipt.get("relationship_sheets") != sheets
                or receipt.get("relationship_properties_sha256") != relation_sheet.properties_digest(sheets)):
            raise model_contract.ContractError("Rendering requires bound resolved relationship sheets")
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
    lines.extend(_configuration_coverage(request))
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
    line_count = max(len(before), len(after))
    context = line_count if line_count <= _SMALL_PROJECTION_LINES else 3
    change = _composition_diff(before, after, context)
    lines = ["# HyperReview — архитектурный эскиз изменения\n",
             ("**Исторический разбор, только локально; публикация отключена.**\n\n"
              if request["intake_mode"] == "historical_read_only" else ""),
             _text(result["summary"]) + "\n",
             "Интерпретация выбранных исходников; порядок узлов не означает порядок выполнения.\n",
             ("`−` и `+` показывают удаление и добавление в соответствующей ветке; "
              "смена родителя тоже выделена, даже если строка узла не изменилась.\n"
              if change else ""),
             (_fence(change, "diff") if change else
              "Структурных изменений в проекции нет. Текущая проекция:\n"
              + _fence(result["after_hc"]))]
    lines.extend(_relation_table(request, result))
    lines.extend(_companion_view(receipt))
    sources = {source["id"]: source for source in request["sources"]}
    address_labels = _address_labels(result)
    for identity in result["identity_map"]:
        refs = list(dict.fromkeys(identity["after_refs"] + identity["before_refs"]))
        links = _compact_source_links(request, _source_groups(refs, sources))
        lines.append(f"- `{address_labels[identity['architecture_id']]}` — {_text(identity['reason'])} "
                     + links + "\n")
    lines.extend(["\n<details>\n<summary>Границы анализа и основания</summary>\n",
                  f"PR #{request['pr']}: `{request['merge_base_sha']}` → `{request['head_sha']}`.\n",
                  f"Исходников в анализе: {len(request['sources'])}; пропущено: {len(request['omissions'])}.\n",
                  "Компилятор проверил структуру Hypercode и ссылки. Соответствие интерпретации коду "
                  "и поведение программы этим не доказаны. Конфигурация описывает заявленную передачу "
                  "данных; её выполнение здесь не наблюдалось. Ссылки на функции и места обращения "
                  "уточнены синтаксически по полученному Python-коду; одинаковое имя само по себе "
                  "не доказывает общее связывание символа или достижимость вызова.\n"])
    lines.extend(_configuration_coverage(request))
    for limitation in [*request["scope"], *request["limitations"], *result["limitations"]]:
        lines.append("- " + _text(limitation) + "\n")
    for omission in request["omissions"]:
        lines.append("- Пропущено: " + _text(omission.get("path") or "путь скрыт политикой")
                     + " — " + _text(omission["reason"]) + ".\n")
    lines.extend(_identity_source_ranges(request, result, sources, address_labels))
    lines.extend(["\n</details>\n", "**Ок или не ок?**\n"])
    return "\n".join(lines).encode("utf-8")
