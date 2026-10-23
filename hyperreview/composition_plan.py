"""Strict provider plan schema and deterministic conversion to a result.

The plan describes architecture nodes and their source provenance. It is never
executed; source text remains untrusted data and is only used as references.
"""

import re

from . import intake, model_contract, relation_plan


PLAN_SCHEMA = "hyperreview.composition-plan.v3"
LEGACY_PLAN_SCHEMA = "hyperreview.composition-plan.v2"
_BARE_ID = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,79}\Z")
_GENERIC_TYPES = frozenset({"file", "pythonfile", "function", "module", "documentation", "comment"})
_MAX_WIRE_BYTES = 1024 * 1024
_MAX_HC_BYTES = 64 * 1024
_NODE_FIELDS = ("reason", "id", "before_type", "after_type", "before_parent", "after_parent",
                "before_refs", "after_refs")
_PLAN_FIELDS = ("schema", "request_digest", "nodes", "summary", "limitations")


class CompositionPlanError(Exception):
    """Raised when a composition plan is malformed or cannot form a tree."""


def _require(condition, message):
    if not condition:
        raise CompositionPlanError(message)


def _id(value, name, *, nullable=False):
    if nullable and value is None:
        return
    _require(type(value) is str and _BARE_ID.fullmatch(value) is not None,
             f"{name} must be a bare identifier of at most 80 characters")


def _canonical_json(value, name):
    try:
        encoded = intake.encoded(value)
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        raise CompositionPlanError(f"{name} is not canonical JSON data") from error
    return encoded


def _validate_plan(plan, request):
    _require(type(plan) is dict and (set(plan) == set(_PLAN_FIELDS)
                                   or set(plan) == set(_PLAN_FIELDS) | {"relations"}
                                   or set(plan) == set(_PLAN_FIELDS) | {"relations", "relation_summary"}),
             "Plan has missing or unknown top-level fields")
    encoded = _canonical_json(plan, "Plan")
    _require(len(encoded) <= _MAX_WIRE_BYTES, "Encoded composition plan exceeds 1 MiB")

    try:
        model_contract.validate_request(request)
    except model_contract.ContractError as error:
        raise CompositionPlanError("Request failed the model contract") from error
    _require(plan["schema"] in (PLAN_SCHEMA, LEGACY_PLAN_SCHEMA), "Unsupported composition plan schema")
    if "relations" in plan and plan["schema"] == PLAN_SCHEMA:
        _require(type(plan.get("relation_summary")) is str and 1 <= len(plan["relation_summary"].strip()) <= 1000,
                 "Common relation plan requires a bounded relation_summary")
    else:
        _require("relation_summary" not in plan, "Relation summary requires common relation semantics")
    _require(type(plan["request_digest"]) is str
             and plan["request_digest"] == request["request_digest"],
             "Plan is not bound to this request")
    nodes = plan["nodes"]
    _require(type(nodes) is list and len(nodes) <= 100,
             "Plan nodes must be a list of at most 100 nodes")

    sources = {"before": set(), "after": set()}
    for source in request["sources"]:
        sources[source["side"]].add(source["id"])

    by_id = {}
    order = []
    for index, node in enumerate(nodes):
        _require(type(node) is dict and set(node) == set(_NODE_FIELDS),
                 f"nodes[{index}] has missing or unknown fields")
        node_id = node["id"]
        _id(node_id, f"nodes[{index}].id")
        _require(node_id not in by_id, "Duplicate node identity")
        by_id[node_id] = node
        order.append(node_id)

        for side in ("before", "after"):
            node_type = node[f"{side}_type"]
            _id(node_type, f"nodes[{index}].{side}_type", nullable=True)
            _require(node_type is None or node_type.casefold() not in _GENERIC_TYPES,
                     f"nodes[{index}].{side}_type is a generic container, not a domain responsibility")
            parent = node[f"{side}_parent"]
            _id(parent, f"nodes[{index}].{side}_parent", nullable=True)
            refs = node[f"{side}_refs"]
            _require(type(refs) is list and len(refs) <= 100,
                     f"nodes[{index}].{side}_refs must be a bounded list")
            _require(all(type(ref) is str for ref in refs),
                     f"nodes[{index}].{side}_refs contains malformed values")
            _require(len(refs) == len(set(refs)),
                     f"nodes[{index}].{side}_refs contains duplicate values")
            if node_type is None:
                _require(parent is None and refs == [],
                         f"Absent {side} node must have null parent and no references")
            else:
                _require(bool(refs), f"Present {side} node must have source references")
                for ref in refs:
                    _require(type(ref) is str and ref in sources[side],
                             f"nodes[{index}].{side}_refs contains an unknown or wrong-side source")
        _require(node["before_type"] is not None or node["after_type"] is not None,
                 f"nodes[{index}] is absent on both sides")
        reason = node["reason"]
        _require(type(reason) is str and 1 <= len(reason) <= 2000,
                 f"nodes[{index}].reason must contain 1..2000 characters")

    children = {side: {node_id: [] for node_id in order} for side in ("before", "after")}
    roots = {side: [] for side in ("before", "after")}
    for node_id in order:
        node = by_id[node_id]
        for side in ("before", "after"):
            if node[f"{side}_type"] is None:
                continue
            parent = node[f"{side}_parent"]
            if parent is None:
                roots[side].append(node_id)
            else:
                _require(parent in by_id, f"{side} parent {parent} is missing")
                _require(by_id[parent][f"{side}_type"] is not None,
                         f"{side} parent {parent} is absent on that side")
                _require(parent != node_id, "A node cannot parent itself")
                children[side][parent].append(node_id)

    # The inferred projection can now have its own generated companion sheet,
    # independently of whether the inspected repository contains any .hcs.
    rows = plan.get("relations", [])
    rows = rows if type(rows) is list else []
    selector_context = {
        f"{side}_hcs_present": (request["selector_context"][f"{side}_hcs_present"] or bool(rows))
        for side in ("before", "after")
    }
    role_counts = {
        side: {role: sum(1 for node_id in order if by_id[node_id][f"{side}_type"] == role)
               for role in {by_id[node_id][f"{side}_type"] for node_id in order
                            if by_id[node_id][f"{side}_type"] is not None}}
        for side in ("before", "after")
    }
    rendered = {}
    for side in ("before", "after"):
        lines = []
        visiting = set()
        visited = set()

        def visit(node_id, depth):
            _require(depth <= 32, f"{side} tree exceeds maximum depth 32")
            _require(node_id not in visiting, f"{side} tree contains a cycle")
            _require(node_id not in visited, f"{side} tree contains a repeated node")
            visiting.add(node_id)
            node = by_id[node_id]
            role = node[f"{side}_type"]
            needs_selector = (selector_context[f"{side}_hcs_present"]
                              and role_counts[side][role] > 1)
            suffix = f"#{node_id}" if needs_selector else ""
            lines.append("  " * (depth - 1) + f"{role}{suffix}")
            for child in children[side][node_id]:
                visit(child, depth + 1)
            visiting.remove(node_id)
            visited.add(node_id)

        expected = {node_id for node_id in order if by_id[node_id][f"{side}_type"] is not None}
        _require(not expected or len(roots[side]) == 1,
                 f"Compact {side} composition must have exactly one root")
        for root in roots[side]:
            visit(root, 1)
        _require(visited == expected, f"{side} tree has an orphan or cycle")
        rendered[side] = ("\n".join(lines) + "\n") if lines else "\n"

    before_bytes = len(rendered["before"].encode("utf-8"))
    after_bytes = len(rendered["after"].encode("utf-8"))
    _require(before_bytes <= _MAX_HC_BYTES and after_bytes <= _MAX_HC_BYTES,
             "Rendered Hypercode exceeds 64 KiB")
    return by_id, order, rendered



def require_current_provider_plan(plan):
    """Live providers must supply current relation coverage, including empty rows."""
    _require(type(plan) is dict and set(plan) == set(_PLAN_FIELDS) | {"relations", "relation_summary"},
             "Provider plan has missing or unknown fields")
    _require(plan["schema"] == PLAN_SCHEMA, "Unsupported composition plan schema")


def plan_schema(request, *, include_relations=False):
    """Return a strict provider schema with source references bound to request."""
    try:
        model_contract.validate_request(request)
    except model_contract.ContractError as error:
        raise CompositionPlanError("Request failed the model contract") from error
    source_ids = {side: sorted({source["id"] for source in request["sources"]
                                if source["side"] == side}) for side in ("before", "after")}
    canonical = model_contract.result_schema()["properties"]
    identifier = {"type": "string", "pattern": r"^[A-Za-z][A-Za-z0-9_]{0,79}$", "maxLength": 80}
    node_properties = {
        "reason": {"type": "string", "minLength": 1, "maxLength": 2000,
                   "description": "Write in Russian: the concrete task and what changed/remained. Explain comment changes separately from code behavior. For an inferred rescope/new wrapper, name the relevant existing .hc roles and explain why their scope does not fit; distinguish this from an actual source rename. Never merely unchanged or file changed."},
        "id": {**identifier, "description": "Stable internal identity for this responsibility role; a #selector is rendered only when this side has .hcs and the role repeats."},
        "before_type": {"anyOf": [identifier, {"type": "null"}],
                        "description": "Domain responsibility of this node, not PythonFile, Function, Module, its root/parent role or internal id. Copy the corresponding before-side .hc role for EACH node; distinct named children keep their own names, not repeated root names plus IDs. Infer a name only without a suitable existing role and explain why. Preserve old inline responsibilities even if their extracted file is new. Null means responsibility absent, not new file absent."},
        "after_type": {"anyOf": [identifier, {"type": "null"}],
                       "description": "Domain responsibility of this node: copy its corresponding after-side .hc role, not a root/parent role repeated across descendants. Keep each named shared owner and child distinct; preserve before_type when unchanged. Retain an existing caller separately after delegation. Explain actual renames or inferred new scopes in reason."},
        "before_parent": {"anyOf": [identifier, {"type": "null"}],
                          "description": "Exact id of a declared present before-side node, never a type/role name. Preserve the authored containing path of a reused .hc role; a compact slice cannot graft it under a different owner. Null for the root/absent node. Declare the relevant containing owners."},
        "after_parent": {"anyOf": [identifier, {"type": "null"}],
                         "description": "Exact id of a declared present after-side node, never a type/role name. Preserve the authored containing path of a reused .hc role, including its shared parent. Do not graft a provider under its caller for compactness. Null for root/absence; declare a named shared owner before referencing its id."},
        "before_refs": {"type": "array", "maxItems": 100 if source_ids["before"] else 0,
                         "uniqueItems": True,
                         "description": "Unique before-side source IDs; do not repeat an ID within this array, including for an owner supported by several children.",
                         "items": ({"type": "string", "enum": source_ids["before"]}
                                   if source_ids["before"] else {"type": "string"})},
        "after_refs": {"type": "array", "maxItems": 100 if source_ids["after"] else 0,
                        "uniqueItems": True,
                        "description": "Unique after-side source IDs; do not repeat an ID within this array, including for a shared owner supported by several children.",
                        "items": ({"type": "string", "enum": source_ids["after"]}
                                  if source_ids["after"] else {"type": "string"})},
    }
    for side in ("before", "after"):
        if not source_ids[side]:
            node_properties[f"{side}_type"] = {"type": "null"}
            node_properties[f"{side}_parent"] = {"type": "null"}
    node_schema = {
        "type": "object", "additionalProperties": False,
        "required": list(_NODE_FIELDS), "properties": node_properties,
    }
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": PLAN_SCHEMA, "type": "object", "additionalProperties": False,
        "required": list(_PLAN_FIELDS),
        "properties": {
            "schema": {"type": "string", "const": PLAN_SCHEMA},
            "request_digest": {"type": "string", "const": request["request_digest"]},
            "nodes": {"type": "array", "maxItems": 100, "items": node_schema},
            "summary": {**canonical["summary"], "description": "Russian: start with the actual code/comment difference, then preserved responsibility and knowledge boundary. Do not just describe function purpose."},
            "limitations": {**canonical["limitations"], "description": "Write missing evidence specific to this interpretation in Russian; do not repeat request boilerplate. Check sources[].path/content and omissions before claiming absence. Name exact missing target files/symbols; distinguish supplied tests of the tool from unavailable tests it references. Partial excerpts are not wholly absent files. Check each referenced path/symbol separately; supplied or excerpted implementations prevent claiming all binding targets are missing. Describe unavailable content, not an assumed missing identifier. Source availability, comparison coverage and observed execution are separate gaps."},
        },
    }
    # Existing callers and retained node-only plans remain supported. Live
    # providers explicitly request the source-bound explanation extension.
    if include_relations:
        schema["required"].append("relations")
        schema["properties"]["relations"] = relation_plan.schema(request)
        schema["required"].append("relation_summary")
        schema["properties"]["relation_summary"] = {
            "type": "string", "minLength": 1, "maxLength": 1000,
            "description": "Russian: summarize the selected consequential connections. If relations=[], explain why no useful supported connection was found or which evidence is missing. Empty does not mean no relationships exist. Do not invent a link to fill a quota."}
        schema["properties"]["limitations"]["maxItems"] = 99
    return schema


def to_result(plan, request):
    """Validate a plan and convert it to the canonical provider-neutral result."""
    try:
        by_id, order, rendered = _validate_plan(plan, request)
        identity_map = []
        for node_id in order:
            node = by_id[node_id]
            identity_map.append({
                "architecture_id": "#" + node_id,
                "before_role": node["before_type"],
                "after_role": node["after_type"],
                "before_refs": list(node["before_refs"]),
                "after_refs": list(node["after_refs"]),
                "reason": node["reason"],
            })
        _require(type(plan["limitations"]) is list, "Plan limitations must be a list")
        limitations = list(plan["limitations"])
        if plan.get("relations") == [] and plan["schema"] == PLAN_SCHEMA:
            limitations.append(relation_plan.EMPTY_PREFIX + plan["relation_summary"].strip())
        result = {
            "schema": model_contract.RESULT_SCHEMA,
            "request_digest": request["request_digest"],
            "before_hc": rendered["before"],
            "after_hc": rendered["after"],
            "identity_map": identity_map,
            "claims": relation_plan.to_claims(plan.get("relations", []), request, identity_map,
                                              legacy=plan["schema"] == LEGACY_PLAN_SCHEMA),
            "summary": plan["summary"],
            "limitations": limitations,
        }
        result_bytes = _canonical_json(result, "Canonical result")
        _require(len(result_bytes) <= _MAX_WIRE_BYTES, "Encoded canonical result exceeds 1 MiB")
        model_contract.validate_result(result, request)
        return result
    except CompositionPlanError:
        raise
    except relation_plan.BindingEvidenceError as error:
        raise CompositionPlanError("Verified binding target absent from cited side") from error
    except ValueError as error:
        raise CompositionPlanError("Invalid source-bound relation plan") from error
    except model_contract.ContractError as error:
        raise CompositionPlanError("Converted result failed the canonical result contract") from error
