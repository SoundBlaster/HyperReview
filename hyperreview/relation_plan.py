"""Source-bound explanation rows, separate from Hypercode containment.

Rows are model interpretations. Reference validation establishes provenance
integrity, never that an edge is true or that a workflow actually ran.
"""


import re

from . import callsite_navigation


MAX_RELATIONS = 6
EMPTY_PREFIX = "Связи не сформированы: "
LEGACY_KINDS = ("calls", "uses_facts", "reuses_policy", "transfers_artifact", "binds_obligation")
KINDS = ("depends_on", "calls", "shared_contract", "data_flow", "requires", "available_when", "reuses_rule", "verified_by")
_LABELS = {"depends_on": "зависимость", "calls": "вызов операции",
           "shared_contract": "общий контракт данных", "data_flow": "передача данных",
           "requires": "обязательство границы", "available_when": "условие доступности",
           "reuses_rule": "переиспользование правила", "verified_by": "заявленная привязка проверки"}


def decode_claim_id(value):
    """Decode frozen legacy and versioned common relation identities."""
    match = re.fullmatch(r"relation-(v2-)?([a-z_]+)-([1-9][0-9]*)", value)
    if match is None:
        raise ValueError("relationship claim identity is invalid")
    kinds = KINDS if match.group(1) else LEGACY_KINDS
    if match.group(2) not in kinds:
        raise ValueError("relationship claim kind is invalid for its version")
    return match.group(2), int(match.group(3))


_FIELDS = {"owner_id", "from", "to", "kind", "side", "basis", "explanation", "source_refs"}
_BASES = ("declaration", "source_analysis")


class BindingEvidenceError(ValueError):
    """An exact verification target is absent from its cited declaration side."""


class CallEndpointError(ValueError):
    """An invocation endpoint visibly lists several operations."""


class LiteralCallerError(ValueError):
    """The indexed literal invocation is in a different named operation."""


class RelationValidationError(ValueError):
    """A closed diagnostic with an application-generated row/field address."""

    def __init__(self, message, code, index, field):
        super().__init__(message)
        self.issue_code = code
        self.issue_location = f" at relations[{index}].{field}"


def compound_call_endpoint(value):
    """Recognize explicit lists outside signatures, not semantic call binding.

    This narrow formatting check leaves arguments, generic parameters and
    quoted identifiers alone. Passing it does not establish a real call.
    """
    stack, quote, escaped, surface = [], None, False, []
    pairs = {"(": ")", "[": "]", "{": "}", "<": ">"}
    for char in value:
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in "\"'`":
            quote = char
        elif char in pairs:
            stack.append(pairs[char])
        elif stack and char == stack[-1]:
            stack.pop()
        elif not stack:
            surface.append(char)
    return bool(re.search(r"[,;\n\r→]|\s+(?:and|or|и|или)\s+", "".join(surface)))


def schema(request):
    refs = sorted(source["id"] for source in request["sources"])
    label = {"type": "string", "minLength": 1, "maxLength": 160}
    return {
        "type": "array", "maxItems": MAX_RELATIONS,
        "description": (
            "Up to six important source-supported relationships, separate from the .hc tree. "
            "Ground direction and kind, not just endpoints; containment/coexistence is not integration. "
            "calls: ONE caller -> ONE immediate callee, no lists or hidden-helper shortcuts; retain unresolved literal targets. "
            "shared_contract needs an inspected common interface/schema and sharing sites; reuses_rule needs one actual rule at multiple sites. "
            "verified_by is a declared binding, not a passed check; preserve an exact file/check target without inventing a symbol. "
            "Endpoints need no tree nodes. Attribute-only changes retain composition. Omit unsupported edges; [] is valid. Never claim runtime observation."
        ),
        "items": {
            "type": "object", "additionalProperties": False,
            "required": ["owner_id", "from", "to", "kind", "side", "basis", "explanation", "source_refs"],
            "properties": {
                "owner_id": {"type": "string", "pattern": r"^#[A-Za-z][A-Za-z0-9_]{0,79}$",
                             "maxLength": 81,
                             "description": "# plus the exact id of a declared node present on this side. Its generated .hcs properties carry this relationship; choose the responsible owner, not a new node just for the edge."},
                "from": {**label, "description": "Source-established responsibility, caller, producer, contract or rule. For source_analysis calls: the actual immediate invoking operation visible at the cited callsite, not its upstream caller or an invented Owner::operation label. For depends_on: the actual dependent, not an unrelated portable alternative. For available_when: the gated capability/operation. For reuses_rule: ONE shared rule."},
                "to": {**label, "description": "Dependency, invoked operation (function/service/syscall/policy), consumer, contract, obligation or availability condition. For calls: ONE immediate callee; separate rows for multiple operations. Preserve the literal receiver/unqualified target unless supplied source establishes binding; never infer a hidden wrapper's delegate from a similar operation elsewhere. For depends_on identify what the from endpoint actually depends on, retaining relevant conditions in explanation; optional availability alone is insufficient. For available_when name the actual availability predicate including relevant platform/feature conditions; A enabling B does not imply A is available when B is independently enabled. For shared_contract name an actual common interface/result/schema with inspected sharing sites; a shown producer and consumer suffice. For reuses_rule: several named sites, marking indirect paths. For verified_by: ONE exact verbatim target from the cited side, without truncation, concatenation or explanation. Use separate rows for separate targets. Never copy a newly added target into before."},
                "kind": {"type": "string", "enum": list(KINDS)},
                "side": {"type": "string", "enum": ["before", "after"]},
                "basis": {"type": "string", "enum": list(_BASES),
                          "description": "declaration only when authored architecture/documentation/specification actually declares this connection, not merely both endpoints. source_analysis for a connection supported by inspected implementation/configuration. Neither proves runtime behavior."},
                "explanation": {"type": "string", "minLength": 1, "maxLength": 1000,
                                "description": "Russian: the architectural consequence, named endpoints, what changed and specific gaps. Briefly identify the declaration or inspected call/import/wiring/transfer/constraint supporting this edge's direction and kind, with relevant conditions. For source_analysis calls identify the immediate caller's invocation; if A calls B and B calls C, use separate rows instead of calling A -> C direct. Distinguish declarations from source-established calls; a shared type is not proof of shared behavior. If the edge lacks support, omit the row; a caveat cannot establish it."},
                "source_refs": {"type": "array", "minItems": 1, "maxItems": 8,
                                "uniqueItems": True,
                                "description": "All sources needed to support BOTH endpoints AND this specific edge's direction and kind, on the declared side only. For calls include the immediate caller's callsite, not only endpoint definitions or an overall flow description. Check scope exclusions and conditions; source names alone do not establish a relationship.",
                                "items": {"type": "string", "enum": refs}},
            },
        },
    }


def to_claims(rows, request, identities, *, legacy=False):
    """Convert bounded rows to the existing provider-neutral inferred claims."""
    if type(rows) is not list or len(rows) > MAX_RELATIONS:
        raise ValueError("Relations must be a list of at most six rows")
    source_records = {source["id"]: source for source in request["sources"]}
    sources = {key: source["side"] for key, source in source_records.items()}
    owners = {entry["architecture_id"]: entry for entry in identities}
    claims = []
    for index, row in enumerate(rows):
        if type(row) is not dict or set(row) != _FIELDS:
            raise ValueError("Relation has missing or unknown fields")
        for field, maximum in (("from", 160), ("to", 160), ("explanation", 1000)):
            if type(row[field]) is not str or not 1 <= len(row[field]) <= maximum:
                raise ValueError("Relation text exceeds its bounds")
        if row["side"] not in ("before", "after") or row["basis"] not in _BASES or row["kind"] not in (LEGACY_KINDS if legacy else KINDS):
            raise ValueError("Relation side, basis or kind is invalid")
        owner = row["owner_id"]
        if (type(owner) is not str or owner not in owners
                or owners[owner][f"{row['side']}_role"] is None):
            raise RelationValidationError("Relation owner must be a declared responsibility on its side",
                                          "relation_owner", index, "owner_id")
        refs = row["source_refs"]
        if type(refs) is not list or not 1 <= len(refs) <= 8 or any(type(ref) is not str for ref in refs):
            raise RelationValidationError("Relation requires bounded source references",
                                          "missing_refs", index, "source_refs")
        if len(refs) != len(set(refs)):
            raise RelationValidationError("Relation source_refs contains duplicate values",
                                          "duplicate_refs", index, "source_refs")
        if any(sources.get(ref) != row["side"] for ref in refs):
            raise RelationValidationError("Relation requires supplied same-side source references",
                                          "unknown_wrongside_ref", index, "source_refs")
        if not legacy and row["kind"] == "calls" and row["basis"] == "source_analysis":
            if any(compound_call_endpoint(row[field]) for field in ("from", "to")):
                raise CallEndpointError("Call endpoints must name one operation each")
            if callsite_navigation.conflicting_literal_caller(row, request):
                raise LiteralCallerError("Literal callsite names another enclosing operation")
        if not legacy and row["kind"] == "verified_by" and row["basis"] == "declaration":
            # Literal presence is only a necessary evidence condition. Token
            # boundaries reject shortened identifiers; a complete test body
            # or merely a similar name cannot establish a declared binding.
            target = re.escape(row["to"])
            pattern = re.compile(r"(?<![\w./:-])" + target + r"(?![\w.:-])")
            if not any(pattern.search(source_records[ref]["content"]) for ref in refs):
                raise BindingEvidenceError("Verified binding target absent from cited side")
        side = "До" if row["side"] == "before" else "После"
        basis = "заявлено в источниках" if row["basis"] == "declaration" else "интерпретация исходников"
        kind = ({"calls": "вызов политики", "uses_facts": "типизированные факты",
                "reuses_policy": "переиспользование правила", "transfers_artifact": "передача артефакта",
                "binds_obligation": "привязка обязательства"} if legacy else _LABELS)[row["kind"]]
        claims.append({
            "id": f"relation-{'' if legacy else 'v2-'}{row['kind']}-{index + 1}",
            "text": f"{row['from']} → {row['to']}",
            "evidence_status": "inferred", "architecture_ids": [owner],
            "source_refs": list(refs),
            "scope": f"{side}; {basis}; {kind}. {row['explanation']}",
            "limitations": ["Проверены ссылки на выбранные исходники; смысл связи и её выполнение этим не доказаны."],
        })
    return claims
