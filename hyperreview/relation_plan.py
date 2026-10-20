"""Source-bound explanation rows, separate from Hypercode containment.

Rows are model interpretations. Reference validation establishes provenance
integrity, never that an edge is true or that a workflow actually ran.
"""


MAX_RELATIONS = 6
_FIELDS = {"owner_id", "from", "to", "kind", "side", "basis", "explanation", "source_refs"}
_KINDS = ("calls", "uses_facts", "reuses_policy", "transfers_artifact", "binds_obligation")
_BASES = ("declaration", "source_analysis")


def schema(request):
    refs = sorted(source["id"] for source in request["sources"])
    label = {"type": "string", "minLength": 1, "maxLength": 160}
    return {
        "type": "array", "maxItems": MAX_RELATIONS,
        "description": (
            "Up to six important source-supported relationships, separate from the .hc tree. "
            "Prioritize one shared rule -> multiple named application sites when inspected; distinguish direct from indirect reuse. Also show obligation -> policy -> application, typed facts, and build/artifact/deploy boundaries. "
            "Endpoints can name an obligation or source-established symbol without adding tree nodes. "
            "Use [] if no relationship has evidence; never invent execution or claim runtime observation."
        ),
        "items": {
            "type": "object", "additionalProperties": False,
            "required": ["owner_id", "from", "to", "kind", "side", "basis", "explanation", "source_refs"],
            "properties": {
                "owner_id": {"type": "string", "pattern": r"^#[A-Za-z][A-Za-z0-9_]{0,79}$",
                             "maxLength": 81,
                             "description": "# plus the exact id of a declared node present on this side. Its generated .hcs properties carry this relationship; choose the responsible owner, not a new node just for the edge."},
                "from": {**label, "description": "For calls: the caller function. For reuses_policy: ONE shared rule symbol."},
                "to": {**label, "description": "For calls: the callee policy. For reuses_policy: at least two named application sites; mark via another policy when indirect."},
                "kind": {"type": "string", "enum": list(_KINDS)},
                "side": {"type": "string", "enum": ["before", "after"]},
                "basis": {"type": "string", "enum": list(_BASES),
                          "description": "declaration for spec/bindings; source_analysis for inspected calls/configuration. Neither proves runtime behavior."},
                "explanation": {"type": "string", "minLength": 1, "maxLength": 1000,
                                "description": "Russian: what this link establishes, named callsites/jobs/obligations, what changed, and any missing part. Distinguish declared bindings from actual policy callsites."},
                "source_refs": {"type": "array", "minItems": 1, "maxItems": 8,
                                "uniqueItems": True,
                                "description": "All sources needed to support BOTH endpoints and this relationship, on the declared side only.",
                                "items": {"type": "string", "enum": refs}},
            },
        },
    }


def to_claims(rows, request, identities):
    """Convert bounded rows to the existing provider-neutral inferred claims."""
    if type(rows) is not list or len(rows) > MAX_RELATIONS:
        raise ValueError("Relations must be a list of at most six rows")
    sources = {source["id"]: source["side"] for source in request["sources"]}
    owners = {entry["architecture_id"]: entry for entry in identities}
    claims = []
    for index, row in enumerate(rows):
        if type(row) is not dict or set(row) != _FIELDS:
            raise ValueError("Relation has missing or unknown fields")
        for field, maximum in (("from", 160), ("to", 160), ("explanation", 1000)):
            if type(row[field]) is not str or not 1 <= len(row[field]) <= maximum:
                raise ValueError("Relation text exceeds its bounds")
        if row["side"] not in ("before", "after") or row["basis"] not in _BASES or row["kind"] not in _KINDS:
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
        side = "До" if row["side"] == "before" else "После"
        basis = "заявлено в источниках" if row["basis"] == "declaration" else "интерпретация исходников"
        kind = {"calls": "вызов политики", "uses_facts": "типизированные факты",
                "reuses_policy": "переиспользование правила", "transfers_artifact": "передача артефакта",
                "binds_obligation": "привязка обязательства"}[row["kind"]]
        claims.append({
            "id": f"relation-{row['kind']}-{index + 1}",
            "text": f"{row['from']} → {row['to']}",
            "evidence_status": "inferred", "architecture_ids": [owner],
            "source_refs": list(refs),
            "scope": f"{side}; {basis}; {kind}. {row['explanation']}",
            "limitations": ["Проверены ссылки на выбранные исходники; смысл связи и её выполнение этим не доказаны."],
        })
    return claims
