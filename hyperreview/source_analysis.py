"""Bounded syntax and literal-declaration navigation for HyperReview hints.

These helpers report syntax-level references only. They do not establish that a
rule is semantically equivalent across call sites, or that a call executes.
"""

import ast
import difflib
import re
from pathlib import PurePosixPath


MAX_SOURCE_BYTES = 256 * 1024
MAX_RESULTS = 4
_IDENTIFIER = re.compile(r"\b[A-Za-z_]\w*\b")
_CORE_NODE = re.compile(r"( *)([A-Za-z_][A-Za-z0-9_]*)(?:\.[A-Za-z_][A-Za-z0-9_]*)*(?:#[A-Za-z_][A-Za-z0-9_]*)? *")


def literal_authored_paths(source):
    """Return positive, unique role paths for a plain core .hc prefix.

    Unknown syntax, tabs, offset windows or multiple roots disable this helper.
    This does not validate Hypercode or establish absent roles or cross-map IDs.
    """
    if (not source["path"].endswith(".hc") or source["line_start"] != 1
            or len(source["content"].encode("utf-8")) > MAX_SOURCE_BYTES):
        return {}
    paths, duplicates, stack = {}, set(), []
    roots = 0
    for line in source["content"].splitlines():
        if not line.strip() or line.lstrip().startswith(("//", "# ")):
            continue
        match = _CORE_NODE.fullmatch(line)
        if match is None:
            return {}
        indent, role = len(match[1]), match[2]
        while stack and stack[-1][0] >= indent:
            stack.pop()
        if not stack:
            roots += 1
            if roots > 1 or indent:
                return {}
        path = tuple(value[1] for value in stack) + (role,)
        if role in paths:
            duplicates.add(role)
        paths[role] = path
        stack.append((indent, role))
    return {role: path for role, path in paths.items() if role not in duplicates
            and not any(ancestor in duplicates for ancestor in path)}


def authored_map_hints(request):
    """Index literal .hc declarations near map edits, with same-side lines.

    This deliberately recognizes only plain core node lines. It is navigation,
    not a Hypercode parser, identity resolver or a complete absence check.
    """
    maps = {}
    for source in request["sources"]:
        if (PurePosixPath(source["path"]).suffix == ".hc"
                and len(source["content"].encode("utf-8")) <= MAX_SOURCE_BYTES):
            maps.setdefault(source["path"], {}).setdefault(source["side"], []).append(source)
    for path, sides in sorted(maps.items()):
        if any(len(records) != 1 for records in sides.values()):
            continue  # Do not align ambiguous or differently windowed records.
        records = {side: values[0] for side, values in sides.items()}
        lines = {side: record["content"].splitlines() for side, record in records.items()}
        if any(len(lines[side]) != record["line_end"] - record["line_start"] + 1
               for side, record in records.items()):
            continue
        focus = {side: set() for side in records}
        if (set(records) == {"before", "after"}
                and records["before"]["line_start"] == records["after"]["line_start"]
                and max(map(len, lines.values())) <= 512):
            matcher = difflib.SequenceMatcher(None, lines["before"], lines["after"], autojunk=False)
            for tag, a, b, c, d in matcher.get_opcodes():
                if tag != "equal":
                    for side, lower, upper in (("before", a, b), ("after", c, d)):
                        focus[side].update(range(max(0, lower - 4), min(len(lines[side]), upper + 4)))
        for side, record in records.items():
            declarations = []
            for index, line in enumerate(lines[side]):
                if _CORE_NODE.fullmatch(line):
                    declarations.append((index, line))
            selected = sorted(declarations, key=lambda row: (row[0] not in focus[side], row[0]))[:24]
            if selected:
                yield {"source_id": record["id"], "path": path, "side": side,
                       "declarations": [f"{record['line_start'] + index}: {line}"
                                        for index, line in sorted(selected)],
                       "partial_index": True}


def _source_tree(source):
    """Return (tree, content, line bounds) for a bounded Python source record."""
    if not isinstance(source, dict):
        return None
    path = source.get("path")
    content = source.get("content")
    start = source.get("line_start")
    end = source.get("line_end")
    if (not isinstance(path, str) or not path.endswith(".py")
            or not isinstance(content, str)
            or type(start) is not int or type(end) is not int
            or start < 1 or end < start):
        return None
    try:
        if len(content.encode("utf-8")) > MAX_SOURCE_BYTES:
            return None
        tree = ast.parse(content, filename=path)
    except (SyntaxError, ValueError, UnicodeError, RecursionError, MemoryError):
        return None
    actual_end = start + max(1, len(content.splitlines())) - 1
    if actual_end != end:
        return None
    return tree, content, start, end


def _span(node, line_offset, lower, upper):
    """Map an AST node to absolute source lines, rejecting out-of-record spans."""
    first = getattr(node, "lineno", None)
    last = getattr(node, "end_lineno", None) or first
    if type(first) is not int or type(last) is not int:
        return None
    first += line_offset
    last += line_offset
    if first < lower or last > upper or first > last:
        return None
    return first, last


def _targets(target):
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        result = []
        for item in target.elts:
            result.extend(_targets(item))
        return result
    return []


def _is_rule_name(name):
    return isinstance(name, str) and name.endswith("_SPEC") and name.isupper()


class _PolicyVisitor(ast.NodeVisitor):
    def __init__(self, source):
        self.source = source
        self.containers = []
        self.function_depth = 0
        self.module_assignment = None
        self.references = {}

    def _visit_function(self, node):
        # Decorators and defaults execute in the containing scope.
        for decorator in node.decorator_list:
            self.visit(decorator)
        for default in list(node.args.defaults) + [value for value in node.args.kw_defaults
                                                    if value is not None]:
            self.visit(default)
        self.containers.append(node.name)
        self.function_depth += 1
        for statement in node.body:
            self.visit(statement)
        self.function_depth -= 1
        self.containers.pop()

    def visit_FunctionDef(self, node):
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node):
        self._visit_function(node)

    def visit_ClassDef(self, node):
        for item in node.decorator_list + node.bases + [keyword.value for keyword in node.keywords]:
            self.visit(item)
        self.containers.append(node.name)
        for statement in node.body:
            self.visit(statement)
        self.containers.pop()

    def visit_Lambda(self, node):
        for default in list(node.args.defaults) + [value for value in node.args.kw_defaults
                                                    if value is not None]:
            self.visit(default)
        self.visit(node.body)

    def _visit_assignment(self, targets, value):
        prior = self.module_assignment
        if not self.containers and targets:
            self.module_assignment = targets[0]
        self.visit(value)
        self.module_assignment = prior

    def visit_Assign(self, node):
        self._visit_assignment([name for target in node.targets for name in _targets(target)],
                               node.value)

    def visit_AnnAssign(self, node):
        names = _targets(node.target)
        self.visit(node.target)
        self.visit(node.annotation)
        prior = self.module_assignment
        if not self.containers and names:
            self.module_assignment = names[0]
        if node.value is not None:
            self.visit(node.value)
        self.module_assignment = prior

    def visit_NamedExpr(self, node):
        self.visit(node.target)
        prior = self.module_assignment
        names = _targets(node.target)
        if not self.containers and names:
            self.module_assignment = names[0]
        self.visit(node.value)
        self.module_assignment = prior

    def visit_Name(self, node):
        if not isinstance(node.ctx, ast.Load) or not _is_rule_name(node.id):
            return
        if self.function_depth:
            scope = ".".join(self.containers)
        elif not self.containers and self.module_assignment:
            scope = self.module_assignment
        else:
            return
        if not scope:
            return
        span = _span(node, self.source["line_start"] - 1,
                     self.source["line_start"], self.source["line_end"])
        if span is not None:
            self.references.setdefault(node.id, []).append((scope, span))


def policy_reuse_hints(request):
    """Find repeated syntactic uses of ``*_SPEC`` names on one revision side.

    A hint requires at least two distinct (source, enclosing function or
    module-level assignment) scopes. At most four hints and four locations per
    hint are returned. This is a mechanical reuse signal, not a semantic claim.
    """
    if not isinstance(request, dict) or not isinstance(request.get("sources"), list):
        return []
    by_rule = {"after": {}, "before": {}}
    for source in request["sources"]:
        if not isinstance(source, dict) or source.get("side") not in by_rule:
            continue
        path = source.get("path", "")
        parts = path.split("/") if isinstance(path, str) else []
        # A verification call is not a second production application path.
        if ("tests" in parts or (parts and (parts[-1].startswith("test_")
                                             or parts[-1].endswith("_test.py")))):
            continue
        parsed = _source_tree(source)
        if parsed is None or not isinstance(source.get("id"), str):
            continue
        tree = parsed[0]
        visitor = _PolicyVisitor(source)
        try:
            visitor.visit(tree)
        except (RecursionError, MemoryError):
            continue
        side_rules = by_rule[source["side"]]
        for rule, references in visitor.references.items():
            sites = side_rules.setdefault(rule, {})
            for scope, span in references:
                key = (source["id"], scope)
                sites.setdefault(key, {"source_id": source["id"], "symbol": scope,
                                       "line_start": span[0], "line_end": span[1]})
    result = []
    for side in ("after", "before"):
        for rule in sorted(by_rule[side]):
            sites = list(by_rule[side][rule].values())
            if len(sites) < 2:
                continue
            sites.sort(key=lambda site: (site["source_id"], site["line_start"], site["symbol"]))
            result.append({"rule": rule, "side": side, "sites": sites[:MAX_RESULTS]})
            if len(result) == MAX_RESULTS:
                return result
    return result


def _parents(tree):
    result = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            result[child] = parent
    return result


def _definition_nodes(tree, mentioned):
    definitions = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name in mentioned:
                definitions.setdefault(node.name, []).append(node)
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
            targets = (node.targets if isinstance(node, ast.Assign) else [node.target])
            for target in targets:
                for name in _targets(target):
                    if name in mentioned and _is_rule_name(name):
                        definitions.setdefault(name, []).append(node)
    return definitions


def _qualified_function(node, parents):
    names = []
    parent = parents.get(node)
    while parent is not None:
        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(parent.name)
        parent = parents.get(parent)
    return ".".join(reversed(names))


def _enclosing_assignment(node, parents):
    parent = parents.get(node)
    while parent is not None:
        if isinstance(parent, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
            targets = parent.targets if isinstance(parent, ast.Assign) else [parent.target]
            names = [name for target in targets for name in _targets(target)]
            if names:
                return names[0]
        parent = parents.get(parent)
    return None


def _call_for_reference(node, parents):
    child = node
    parent = parents.get(child)
    while parent is not None and isinstance(parent, (ast.Attribute, ast.Subscript)):
        child, parent = parent, parents.get(parent)
    if isinstance(parent, ast.Call) and child in ast.walk(parent.func):
        return parent
    return None


def _declaration_spans(source, text):
    """Locate literal named declarations, without interpreting their semantics."""
    if (not isinstance(source, dict) or not isinstance(text, str)
            or not isinstance(source.get("path"), str)
            or PurePosixPath(source["path"]).suffix not in
            (".md", ".hc", ".hcs", ".yaml", ".yml", ".json", ".toml")):
        return []
    content = source.get("content")
    start, end = source.get("line_start"), source.get("line_end")
    if not isinstance(content, str) or type(start) is not int or type(end) is not int:
        return []
    try:
        if len(content.encode("utf-8")) > MAX_SOURCE_BYTES:
            return []
    except UnicodeError:
        return []
    lines = content.split("\n")
    if lines[-1] == "":
        lines.pop()
    if start < 1 or len(lines) != end - start + 1:
        return []
    names = set(re.findall(r"\b[A-Za-z][A-Za-z0-9_-]{2,}\b", text))
    names = {name for name in names if "_" in name or "-" in name
             or re.search(r"[a-z][A-Z]", name) or name.isupper()}
    names.update(re.findall(r"\b[A-Za-z][A-Za-z0-9_-]*(?:\.[A-Za-z][A-Za-z0-9_-]*)+\b", text))
    candidates = []
    seen = set()
    for index, line in enumerate(lines):
        matches = sorted(name for name in names if re.search(
            r"(?<![A-Za-z0-9_.-])" + re.escape(name) + r"(?![A-Za-z0-9_.-])", line))
        if not matches:
            continue
        lower, upper = max(0, index - 1), min(len(lines), index + 3)
        declaration = re.match(r"^(\s*)-\s+id:\s*['\"]?([A-Za-z][A-Za-z0-9_.-]+)", line)
        is_declaration = declaration and declaration.group(2) in matches
        if is_declaration:
            lower, upper = index, index + 1
            indent = len(declaration.group(1))
            while upper < min(len(lines), index + 24):
                following = lines[upper]
                if following.strip() and len(following) - len(following.lstrip()) <= indent:
                    break
                upper += 1
        span = (lower + start, upper + start - 1)
        if span in seen:
            continue
        seen.add(span)
        priority = (2 if is_declaration else 0) + int(any(len(name) >= 24 for name in matches))
        candidates.append((priority, {"label": ", ".join(matches), "line_start": span[0], "line_end": span[1]}))
    result = []
    for _priority, item in sorted(candidates, key=lambda pair: (-pair[0], pair[1]["line_start"])):
        if any(value["line_start"] <= item["line_start"] and value["line_end"] >= item["line_end"]
               for value in result):
            continue
        result.append(item)
        if len(result) == MAX_RESULTS:
            break
    return sorted(result, key=lambda value: value["line_start"])


def _code_literal_spans(source, text):
    """Find bounded literal identifier windows in other supplied code formats.

    These are lexical anchors, not parsed definitions or resolved calls. No
    language adapter is required, and an unmatched claim keeps its full range.
    """
    if not isinstance(source, dict) or not isinstance(source.get("path"), str):
        return []
    if PurePosixPath(source["path"]).suffix in (".md", ".hc", ".hcs", ".yaml", ".yml", ".json", ".toml", ".py"):
        return []
    content, start, end = source.get("content"), source.get("line_start"), source.get("line_end")
    if not isinstance(content, str) or type(start) is not int or type(end) is not int or start < 1:
        return []
    if len(content.encode("utf-8")) > MAX_SOURCE_BYTES:
        return []
    lines = content.splitlines()
    if len(lines) != end - start + 1:
        return []
    names = {name for name in _IDENTIFIER.findall(text)
             if "_" in name or re.search(r"[a-z][A-Z]", name)
             or (len(name) > 2 and name[0].isupper())}
    windows = []
    for index, line in enumerate(lines):
        if line.lstrip().startswith(("//", "/*", "*", "# ")):
            continue
        matches = sorted(name for name in names if re.search(
            r"(?<![A-Za-z0-9_])" + re.escape(name) + r"(?![A-Za-z0-9_])", line))
        if not matches:
            continue
        stop = min(len(lines), index + 3)
        # Retain nearby multiline arguments rather than citing only the call
        # name. This is bounded lexical navigation, not a language parser.
        balance = line.count("(") - line.count(")")
        cursor = index + 1
        while balance > 0 and cursor < min(len(lines), index + 14):
            balance += lines[cursor].count("(") - lines[cursor].count(")")
            cursor += 1
        stop = max(stop, cursor)
        lower, upper = max(0, index - 2) + start, stop + start - 1
        if windows and lower <= windows[-1]["line_end"] + 1:
            previous = windows[-1]
            # Keep navigation windows bounded even for repeatedly used names.
            if upper - previous["line_start"] < 16:
                previous["line_end"] = upper
                previous["label"] = ", ".join(sorted(set(previous["label"].split(", ")) | set(matches)))
                continue
        if len(windows) == MAX_RESULTS:
            break
        windows.append({"label": ", ".join(matches), "line_start": lower, "line_end": upper})
    return windows


def citation_spans(source, text):
    """Return up to four syntax/literal spans for identifiers named in ``text``.

    Python uses parsed AST locations; other formats use exact literal anchors.
    Absolute lines remain within the supplied record. Neither method
    establishes semantic binding, dynamic dispatch or execution.
    """
    if not isinstance(text, str):
        return []
    parsed = _source_tree(source)
    if parsed is None:
        return _declaration_spans(source, text) or _code_literal_spans(source, text)
    tree, _content, start, end = parsed
    mentioned = set(_IDENTIFIER.findall(text))
    if not mentioned:
        return []
    parents = _parents(tree)
    definitions = _definition_nodes(tree, mentioned)
    preferred = []
    fallback = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Name) or not isinstance(node.ctx, ast.Load):
            continue
        name = node.id
        if not _is_rule_name(name) or name not in mentioned:
            continue
        call = _call_for_reference(node, parents)
        function = _qualified_function(node, parents)
        span_node = call or node
        span = _span(span_node, start - 1, start, end)
        if span is None:
            continue
        if call is not None and function:
            label = function
            preferred.append((span[0], span[1], label))
        else:
            caller = function or _enclosing_assignment(node, parents)
            label = f"{caller} / {name}" if caller else name
            fallback.append((span[0], span[1], label))
    # Keep intermediate policy composition references alongside function calls.
    # A concrete call must not hide the assignment that establishes an indirect
    # path in the same file. Whole definitions are only a navigation fallback.
    candidates = preferred + fallback
    if not candidates:
        for name, nodes in definitions.items():
            for node in nodes:
                span = _span(node, start - 1, start, end)
                if span is not None:
                    candidates.append((span[0], span[1], name))
    unique = []
    seen = set()
    for line_start, line_end, label in sorted(candidates, key=lambda item: (item[0], item[1], item[2])):
        key = (label, line_start, line_end)
        if key in seen:
            continue
        seen.add(key)
        unique.append({"label": label, "line_start": line_start, "line_end": line_end})
        if len(unique) == MAX_RESULTS:
            break
    return unique
