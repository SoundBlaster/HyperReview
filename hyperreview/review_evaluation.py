"""Controlled, source-bound observations for native MLflow GenAI evaluation.

These are deterministic witnesses, not a semantic judge. Full artifacts and
rubrics remain local; SDK adapters receive only fixed numeric fields/digests.
"""

import hashlib
import re

from . import intake, source_analysis
from .evaluation_delivery import _trusted_input_file, _trusted_path
from .storage import read_json


SUITE_SCHEMA = "hyperreview.review-suite.v1"
PAIR_SCHEMA = "hyperreview.review-pairs.v1"
REPORT_SCHEMA = "hyperreview.review-comparison.v1"
METRIC_VERSION = "review-witnesses-v3"
METRICS = ("source_retention", "relation_presence", "containment_preserved", "compiler_receipt_consistent",
           "forbidden_relation_absent")
ID = re.compile(r"case-[0-9]{3}\Z")
CHECK_ID = re.compile(r"check-[0-9]{3}\Z")
SHA = re.compile(r"[a-f0-9]{64}\Z")
KINDS = frozenset(("calls", "depends_on", "data_flow", "requires", "available_when",
                   "shared_contract", "reuses_rule", "verified_by"))
AXES = frozenset(("intake", "explanation", "model"))


class ReviewEvaluationError(Exception):
    """Invalid comparison, lineage or bounded artifact input."""


def require(condition, message):
    if not condition:
        raise ReviewEvaluationError(message)


def _text(value, maximum=512):
    return type(value) is str and 0 < len(value) <= maximum and not any(ord(c) < 32 for c in value)


def validate_suite(suite):
    require(type(suite) is dict and set(suite) == {"schema", "version", "cases"}
            and suite["schema"] == SUITE_SCHEMA and _text(suite["version"], 80), "Invalid review suite")
    require(type(suite["cases"]) is list and 1 <= len(suite["cases"]) <= 16, "Invalid case count")
    seen = set()
    for case in suite["cases"]:
        require(type(case) is dict and set(case) == {"id", "repository", "pr", "base", "head", "checks", "rubric"},
                "Invalid case fields")
        require(type(case["id"]) is str and ID.fullmatch(case["id"]) and case["id"] not in seen,
                "Invalid or duplicate case ID")
        seen.add(case["id"])
        require(case["repository"] in intake.ALLOWLIST and type(case["pr"]) is int and case["pr"] > 0,
                "Invalid case repository/PR")
        require(all(type(case[k]) is str and re.fullmatch(r"[a-f0-9]{40}", case[k]) for k in ("base", "head")),
                "Invalid pinned revisions")
        require(type(case["rubric"]) is list and 1 <= len(case["rubric"]) <= 8
                and all(_text(value, 2000) for value in case["rubric"]), "Invalid local rubric")
        require(type(case["checks"]) is list and 1 <= len(case["checks"]) <= 16, "Invalid check count")
        check_ids = set()
        for check in case["checks"]:
            require(type(check) is dict and type(check.get("id")) is str
                    and CHECK_ID.fullmatch(check["id"]) and check["id"] not in check_ids, "Invalid check ID")
            check_ids.add(check["id"])
            require(check.get("side") in ("before", "after"), "Invalid check side")
            base = {"id", "kind", "side"}
            if check.get("kind") == "source":
                require(set(check) == base | {"path"} and _text(check["path"])
                        and intake._source_exclusion(check["path"]) is None, "Invalid expected source")
            elif check.get("kind") in ("relation", "relation_absence", "relation_exact"):
                endpoints = ("from_any", "to_any") if check["kind"] == "relation_exact" else ("from_contains", "to_contains")
                require(set(check) == base | {"relation_kind", *endpoints}
                        and check["relation_kind"] in KINDS, "Invalid expected relation")
                for field in endpoints:
                    require(type(check[field]) is list and 1 <= len(check[field]) <= 8
                            and all(_text(value, 160) for value in check[field]), "Invalid endpoint tokens")
            elif check.get("kind") == "containment":
                require(set(check) == base | {"roles"} and type(check["roles"]) is list
                        and 1 <= len(check["roles"]) <= 32
                        and all(type(role) is str and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,79}", role)
                                for role in check["roles"]), "Invalid expected containment")
            else:
                raise ReviewEvaluationError("Unsupported check kind")
    return suite


def _read(directory, name):
    return read_json(_trusted_input_file(directory / name), max_bytes=1024 * 1024)


def load_bundle(path, *, projection):
    """Read historical contracts without pretending they use today's profile."""
    directory = _trusted_path(path, directory=True)
    request, evidence = _read(directory, "request.json"), _read(directory, "evidence.json")
    require(type(request) is dict and type(evidence) is dict, "Invalid artifact objects")
    unsigned = {k: v for k, v in request.items() if k != "request_digest"}
    require(request.get("request_digest") == intake.digest(unsigned), "Request digest mismatch")
    require(evidence.get("evidence_digest") == intake.digest({k: v for k, v in evidence.items()
                                                            if k != "evidence_digest"}), "Evidence digest mismatch")
    require(request.get("evidence_digest") == evidence["evidence_digest"], "Evidence/request mismatch")
    require(type(request.get("sources")) is list and len(request["sources"]) <= 60, "Invalid source inventory")
    for source in request["sources"]:
        require(type(source) is dict and type(source.get("content")) is str
                and source.get("side") in ("before", "after")
                and type(source.get("path")) is str
                and intake._source_exclusion(source["path"]) is None
                and source.get("content_sha256") == hashlib.sha256(source["content"].encode()).hexdigest()
                and source.get("revision") == request.get("merge_base_sha" if source["side"] == "before" else "head_sha"),
                "Invalid frozen source")
    files = {"request": request, "evidence": evidence}
    if projection:
        result, receipt, generation = (_read(directory, name) for name in
                                       ("result.json", "compiler-receipt.json", "generation-receipt.json"))
        require(all(type(item) is dict for item in (result, receipt, generation)), "Invalid receipt objects")
        require(result.get("request_digest") == request["request_digest"]
                and receipt.get("request_digest") == request["request_digest"]
                and receipt.get("result_digest") == intake.digest(result)
                and receipt.get("stage") == "projections_validated"
                and generation.get("request_digest") == request["request_digest"]
                and generation.get("result_digest") == intake.digest(result), "Projection receipt mismatch")
        require(type(result.get("claims")) is list and len(result["claims"]) <= 64
                and all(type(claim) is dict and all(type(claim.get(key)) is str
                                                   for key in ("id", "scope", "text"))
                        for claim in result["claims"]), "Invalid claim inventory")
        require(all(_text(generation.get(key), 200) for key in ("provider", "model", "reasoning_effort"))
                and type(generation.get("executable_sha256")) is str
                and SHA.fullmatch(generation["executable_sha256"])
                and generation.get("prompt_version") == request.get("prompt_version")
                and generation.get("reviewer_profile_sha256") == request["reviewer_profile"]["sha256"],
                "Invalid generation lineage")
        require(type(receipt.get("compiler_sha256")) is str and SHA.fullmatch(receipt["compiler_sha256"]),
                "Missing compiler identity")
        for side in ("before", "after"):
            file = _trusted_input_file(directory / f"{side}.hc")
            require(file.stat().st_size <= 65536 and file.read_text() == result.get(f"{side}_hc"),
                    "Projection bytes mismatch")
            ir_file = _trusted_input_file(directory / f"{side}.ir.json")
            require(ir_file.stat().st_size <= 1024 * 1024, "Compiler IR exceeds limit")
            require(receipt.get(f"{side}_ir_sha256") == hashlib.sha256(ir_file.read_bytes()).hexdigest(),
                    "Compiler IR digest mismatch")
        files.update(result=result, receipt=receipt, generation=generation)
    return {**files, "digest": intake.digest({key: intake.digest(value) for key, value in files.items()})}


def bundle_digest(path, *, axis):
    require(axis in AXES, "Invalid comparison axis")
    return load_bundle(path, projection=axis != "intake")["digest"]


def _same_model_harness(old, new):
    require(old["request"] == new["request"], "Model comparison requires an identical frozen request/profile")
    require(old["receipt"]["compiler_sha256"] == new["receipt"]["compiler_sha256"],
            "Model comparison changed compiler")
    require(all(old["generation"].get(key) == new["generation"].get(key)
                for key in ("provider", "reasoning_effort", "executable_sha256")),
            "Model comparison changed provider, effort or executable")
    for key in ("reviewer_runtime_sha256", "provider_schema_sha256", "system_prompt_sha256", "result_schema_sha256"):
        value = old["generation"].get(key)
        require(type(value) is str and SHA.fullmatch(value) and value == new["generation"].get(key),
                "Model comparison requires matching runtime, schema and instruction seals")
    budget = old["generation"].get("generation_budget_seconds")
    require(type(budget) is int and 30 <= budget <= 300
            and type(new["generation"].get("generation_budget_seconds")) is int
            and budget == new["generation"]["generation_budget_seconds"],
            "Model comparison requires the same generation budget")


def _contains(endpoint, tokens):
    return all(re.search(r"(?<![A-Za-z0-9_])" + re.escape(token) + r"(?![A-Za-z0-9_])", endpoint)
               for token in tokens)


def _relation_witness(result, check):
    for claim in result["claims"]:
        if not claim["id"].startswith("relation-v2-" + check["relation_kind"] + "-"):
            continue
        if not claim["scope"].startswith("До;" if check["side"] == "before" else "После;"):
            continue
        parts = claim["text"].split(" → ")
        if len(parts) != 2:
            continue
        if check["kind"] == "relation_exact":
            matched = parts[0] in check["from_any"] and parts[1] in check["to_any"]
        else:
            matched = _contains(parts[0], check["from_contains"]) and _contains(parts[1], check["to_contains"])
        if matched:
            return True
    return False


def observe(case, bundle, axis):
    observations = {key: [] for key in METRICS}
    checks = []
    request, result = bundle["request"], bundle.get("result")
    for check in case["checks"]:
        kind = check["kind"]
        if kind == "source":
            value = any(source["path"] == check["path"] and source["side"] == check["side"]
                        for source in request["sources"])
            metric = "source_retention"
        elif result is None:
            checks.append({"id": check["id"], "value": None})
            continue
        elif kind in ("relation", "relation_absence", "relation_exact"):
            present = _relation_witness(result, check)
            value, metric = ((present, "relation_presence") if kind != "relation_absence" else
                             (not present, "forbidden_relation_absent"))
        else:
            hc = result[f"{check['side']}_hc"]
            paths = source_analysis.literal_authored_paths({"path": "projection.hc", "line_start": 1, "content": hc})
            value = paths.get(check["roles"][-1]) == tuple(check["roles"])
            metric = "containment_preserved"
        observations[metric].append(int(value))
        checks.append({"id": check["id"], "value": int(value)})
    observations["compiler_receipt_consistent"] = [1] if result is not None else []
    values = {key: sum(items) / len(items) if items else None for key, items in observations.items()}
    return values, checks


def compare(suite, pairs):
    """Compare sealed artifacts; do not collect, infer, publish or re-render."""
    validate_suite(suite)
    require(type(pairs) is dict and set(pairs) == {"schema", "suite_digest", "pairs"}
            and pairs["schema"] == PAIR_SCHEMA and pairs["suite_digest"] == intake.digest(suite), "Pair/suite mismatch")
    require(type(pairs["pairs"]) is list and 1 <= len(pairs["pairs"]) <= 32, "Invalid pair count")
    cases, rows, details, seen = {case["id"]: case for case in suite["cases"]}, [], [], set()
    for pair in pairs["pairs"]:
        require(type(pair) is dict and set(pair) == {"case_id", "axis", "baseline", "candidate",
                                                    "baseline_digest", "candidate_digest"}, "Invalid pair fields")
        case_id, axis = pair["case_id"], pair["axis"]
        require(case_id in cases and axis in AXES
                and (case_id, axis) not in seen, "Invalid or duplicate pair")
        seen.add((case_id, axis))
        case = cases[case_id]
        loaded = {}
        for variant in ("baseline", "candidate"):
            bundle = load_bundle(pair[variant], projection=axis != "intake")
            require(type(pair[f"{variant}_digest"]) is str and SHA.fullmatch(pair[f"{variant}_digest"])
                    and bundle["digest"] == pair[f"{variant}_digest"], "Sealed artifact changed")
            request = bundle["request"]
            require((request["repository"], request["pr"], request["merge_base_sha"], request["head_sha"])
                    == (case["repository"], case["pr"], case["base"], case["head"]), "Case revision mismatch")
            loaded[variant] = bundle
        old, new = loaded["baseline"], loaded["candidate"]
        if axis == "explanation":
            ignored = {"request_digest", "prompt_version", "reviewer_profile"}
            require({k: v for k, v in old["request"].items() if k not in ignored}
                    == {k: v for k, v in new["request"].items() if k not in ignored},
                    "Explanation comparison requires identical frozen inputs")
            require(all(old["generation"].get(key) == new["generation"].get(key)
                        for key in ("provider", "model", "reasoning_effort", "executable_sha256")),
                    "Explanation comparison changed provider/model settings")
            require(old["receipt"].get("compiler_sha256") == new["receipt"].get("compiler_sha256"),
                    "Explanation comparison changed compiler")
        elif axis == "model":
            _same_model_harness(old, new)
        else:
            require(old["request"]["reviewer_profile"] == new["request"]["reviewer_profile"]
                    and old["request"]["prompt_version"] == new["request"]["prompt_version"]
                    and old["evidence"].get("limits") == new["evidence"].get("limits")
                    and all(old["request"]["source_selection"][key] == new["request"]["source_selection"][key]
                            for key in ("mode", "include_paths", "max_source_bytes")),
                    "Intake comparison changed prompt or budgets")
        observations = {}
        for variant, bundle in loaded.items():
            values, checks = observe(case, bundle, axis)
            observations[variant] = {item["id"]: item["value"] for item in checks}
            rows.append({"case_id": case_id, "axis": axis, "variant": variant,
                         "artifact_digest": bundle["digest"], "request_digest": bundle["request"]["request_digest"],
                         "source_digest": intake.digest(bundle["request"]["sources"]),
                         "profile_digest": intake.digest(bundle["request"]["reviewer_profile"]),
                         "model_settings_digest": intake.digest({key: bundle["generation"][key]
                             for key in ("provider", "model", "reasoning_effort", "executable_sha256")})
                             if "generation" in bundle else None,
                         "compiler_sha256": bundle.get("receipt", {}).get("compiler_sha256"),
                         "reviewer_runtime_sha256": bundle.get("generation", {}).get("reviewer_runtime_sha256")
                             if type(bundle.get("generation", {}).get("reviewer_runtime_sha256")) is str
                             and SHA.fullmatch(bundle["generation"]["reviewer_runtime_sha256"]) else None,
                         "generation_budget_seconds": bundle.get("generation", {}).get("generation_budget_seconds")
                             if type(bundle.get("generation", {}).get("generation_budget_seconds")) is int
                             and 30 <= bundle["generation"]["generation_budget_seconds"] <= 300 else None,
                         "outputs": values})
        for check_id, before in observations["baseline"].items():
            after = observations["candidate"][check_id]
            details.append({"case_id": case_id, "axis": axis, "check_id": check_id,
                            "baseline": before, "candidate": after,
                            "regressed": before is not None and after is not None and after < before})
    coverage = {axis: {"paired_cases": sorted(case_id for case_id, selected_axis in seen if selected_axis == axis),
                       "unpaired_cases": sorted(case_id for case_id in cases if (case_id, axis) not in seen)}
                for axis in sorted({axis for _, axis in seen})}
    return {"schema": REPORT_SCHEMA, "suite_digest": intake.digest(suite), "metric_version": METRIC_VERSION,
            "assessor_type": "deterministic_witness", "semantic_assessment": "pending",
            "publication_gate": False, "coverage": coverage, "rows": rows, "checks": details}
