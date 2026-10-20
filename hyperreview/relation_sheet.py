"""Compile source-bound relationship claims into bounded Hypercode sheets."""

import hashlib
import json
import re


_RELATION_ID = re.compile(r"relation-(calls|uses_facts|reuses_policy|transfers_artifact|binds_obligation)-([1-9][0-9]*)\Z")
_ROLE = re.compile(r"[A-Za-z][A-Za-z0-9_-]*\Z")
_IDENTITY = re.compile(r"#[A-Za-z][A-Za-z0-9_.-]*\Z")


def _line(value, limit):
    if type(value) is not str or not value:
        raise ValueError("relationship sheet text is missing")
    value = " ".join(value.split())
    if not value or len(value) > limit or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("relationship sheet text exceeds its bounds")
    return value


def build(request, result):
    """Return side -> sheet metadata for canonical relation claims only."""
    if type(result) is not dict or type(result.get("claims")) is not list:
        raise ValueError("relationship claims are malformed")
    sources = {source["id"]: source["side"] for source in request["sources"]}
    identities = {entry["architecture_id"]: entry for entry in result["identity_map"]}
    role_counts = {side: {} for side in ("before", "after")}
    for entry in result["identity_map"]:
        for side in role_counts:
            role = entry[f"{side}_role"]
            if role is not None:
                role_counts[side][role] = role_counts[side].get(role, 0) + 1

    rows = {"before": [], "after": []}
    property_records = []
    seen = set()
    for claim in result["claims"]:
        claim_id = claim.get("id") if type(claim) is dict else None
        if not isinstance(claim_id, str) or not claim_id.startswith("relation-"):
            continue
        match = _RELATION_ID.fullmatch(claim_id)
        if match is None:
            raise ValueError("relationship claim identity is invalid")
        kind = match.group(1)
        number = int(match.group(2))
        if number > 6 or len(seen) >= 6:
            raise ValueError("relationship sheet exceeds six bounded rows")
        key = f"{kind}_{number}"
        if key in seen:
            raise ValueError("relationship property identity is duplicated")
        seen.add(key)
        refs = claim.get("source_refs")
        if (type(refs) is not list or not 1 <= len(refs) <= 8
                or any(type(ref) is not str for ref in refs) or len(refs) != len(set(refs))):
            raise ValueError("relationship source references are not bounded and unique")
        sides = {sources.get(ref) for ref in refs}
        if len(sides) != 1 or None in sides:
            raise ValueError("relationship sources must resolve to one revision side")
        side = sides.pop()
        owners = claim.get("architecture_ids")
        if type(owners) is not list or len(owners) != 1 or owners[0] not in identities:
            raise ValueError("relationship claim requires one known architecture owner")
        identity = identities[owners[0]]
        role = identity[f"{side}_role"]
        if type(role) is not str or not _ROLE.fullmatch(role):
            raise ValueError("relationship owner has no valid role on its evidence side")
        owner_id = identity["architecture_id"]
        if not _IDENTITY.fullmatch(owner_id):
            raise ValueError("relationship owner identity is invalid")
        selector = role if role_counts[side][role] == 1 else "'" + owner_id + "'"
        values = {
            key: _line(claim.get("text"), 400),
            key + "_scope": _line(claim.get("scope"), 1200),
            key + "_sources": _line(", ".join(refs), 600),
        }
        rows[side].append((selector, owner_id, role, values))
        for property_name, value in values.items():
            property_records.append([side, owner_id, property_name, value])

    sheets = {}
    for side, entries in rows.items():
        if not entries:
            continue
        grouped = {}
        for selector, owner_id, role, values in entries:
            group = grouped.setdefault((selector, owner_id, role), {})
            if set(group) & set(values):
                raise ValueError("relationship properties collide on one owner")
            group.update(values)
        lines = []
        for (selector, _owner_id, _role), values in sorted(grouped.items()):
            lines.append(f"{selector}:")
            for key, value in sorted(values.items()):
                # Hypercode strips only the outer quotes, so values are made
                # single-line and are not JSON-escaped.
                lines.append(f'  {key}: "{value}"')
        content = "\n".join(lines) + "\n"
        sheets[side] = {"content": content,
                        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                        "properties": [record for record in property_records if record[0] == side]}
    return sheets


def effective_selector_context(request, result):
    """Include generated relation sheets in selector provenance requirements."""
    context = dict(request["selector_context"])
    sheets = build(request, result)
    for side in ("before", "after"):
        key = f"{side}_hcs_present"
        context[key] = bool(context[key] or side in sheets)
    return context


def verify_resolved_values(result, sheet, document, side):
    """Check each generated property resolves on exactly its intended node."""
    entries = {entry["architecture_id"]: entry for entry in result["identity_map"]}
    nodes = []
    stack = list(document.get("nodes", []))
    while stack:
        node = stack.pop()
        nodes.append(node)
        stack.extend(node.get("children", []))
    for _sheet_side, owner_id, key, expected in sheet["properties"]:
        identity = entries[owner_id]
        role = identity[f"{side}_role"]
        matches = [node for node in nodes if node.get("type") == role and
                   (node.get("id") == owner_id[1:] if sum(
                       1 for entry in result["identity_map"]
                       if entry[f"{side}_role"] == role) > 1 else node.get("id") is None)]
        if len(matches) != 1:
            raise ValueError("relationship property owner did not resolve uniquely")
        prop = matches[0].get("properties", {}).get(key)
        if type(prop) is not dict or prop.get("value") != expected:
            raise ValueError("relationship sheet property did not resolve to its bound value")


def properties_digest(sheets):
    values = sorted(record for sheet in sheets.values() for record in sheet["properties"])
    return hashlib.sha256(json.dumps(values, ensure_ascii=True, separators=(",", ":"))
                          .encode("utf-8")).hexdigest()
