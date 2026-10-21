"""Source-bound explanation rows, separate from Hypercode containment.

Rows are model interpretations. Reference validation establishes provenance
integrity, never that an edge is true or that a workflow actually ran.
"""


import re


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


def schema(request):
    refs = sorted(source["id"] for source in request["sources"])
    label = {"type": "string", "minLength": 1, "maxLength": 160}
    return {
        "type": "array", "maxItems": MAX_RELATIONS,
        "description": (
            "Up to six important source-supported relationships, separate from the .hc tree. "
            "Explain dependencies, operation calls, shared data contracts, data flow, boundary obligations and availability conditions across any stack. Use reuses_rule only for one actual rule with multiple application sites, not a shared type. "
            "Use verified_by for a declared obligation-to-check binding, never proof the check passed. "
            "On an attribute-only change keep the same .hc composition and describe before/after properties. "
            "Endpoints can name an obligation or source-established symbol without adding tree nodes. "
            "Ground each edge's direction and kind, not just its endpoints. Coexistence, containment or optional availability does not establish a dependency or integration. "
            "For shared_contract identify an actual common interface/result/schema and its inspected sharing sites. Omit an unsupported edge instead of excusing it with a disclaimer. "
            "Use [] if no relationship has evidence; never invent execution or claim runtime observation."
        ),
        "items": {
            "type": "object", "additionalProperties": False,
            "required": ["owner_id", "from", "to", "kind", "side", "basis", "explanation", "source_refs"],
            "properties": {
                "owner_id": {"type": "string", "pattern": r"^#[A-Za-z][A-Za-z0-9_]{0,79}$",
                             "maxLength": 81,
                             "description": "# plus the exact id of a declared node present on this side. Its generated .hcs properties carry this relationship; choose the responsible owner, not a new node just for the edge."},
                "from": {**label, "description": "Source-established responsibility, caller, producer, contract or rule. For calls: the caller; for depends_on: the actual dependent, not an unrelated portable alternative. For reuses_rule: ONE shared rule."},
                "to": {**label, "description": "Dependency, invoked operation (function/service/syscall/policy), consumer, contract, obligation or availability condition. For depends_on identify what the from endpoint actually depends on, retaining relevant conditions in explanation; optional availability alone is insufficient. For shared_contract name an actual common interface/result/schema with inspected sharing sites. For reuses_rule: several named sites, marking indirect paths. For verified_by: ONE exact verbatim target from the cited side, without truncation, concatenation or explanation. Use separate rows for separate targets. Never copy a newly added target into before."},
                "kind": {"type": "string", "enum": list(KINDS)},
                "side": {"type": "string", "enum": ["before", "after"]},
                "basis": {"type": "string", "enum": list(_BASES),
                          "description": "declaration only when authored architecture/documentation/specification actually declares this connection, not merely both endpoints. source_analysis for a connection supported by inspected implementation/configuration. Neither proves runtime behavior."},
                "explanation": {"type": "string", "minLength": 1, "maxLength": 1000,
                                "description": "Russian: the architectural consequence, named endpoints, what changed and specific gaps. Briefly identify the declaration or inspected call/import/wiring/transfer/constraint supporting this edge's direction and kind, with relevant conditions. Distinguish declarations from source-established calls; a shared type is not proof of shared behavior. If the edge lacks support, omit the row; a caveat cannot establish it."},
                "source_refs": {"type": "array", "minItems": 1, "maxItems": 8,
                                "uniqueItems": True,
                                "description": "All sources needed to support BOTH endpoints AND this specific edge's direction and kind, on the declared side only. Check scope exclusions and conditions; source names alone do not establish a relationship.",
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
            raise ValueError("Relation owner must be a declared responsibility on its side")
        refs = row["source_refs"]
        if (type(refs) is not list or not 1 <= len(refs) <= 8
                or any(type(ref) is not str or sources.get(ref) != row["side"] for ref in refs)
                or len(refs) != len(set(refs))):
            raise ValueError("Relation requires unique supplied same-side source references")
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
