"""Small, bounded AST helpers for source-grounded HyperReview hints.

These helpers report syntax-level references only. They do not establish that a
rule is semantically equivalent across call sites, or that a call executes.
"""

import ast
import re


MAX_SOURCE_BYTES = 256 * 1024
MAX_RESULTS = 4
_IDENTIFIER = re.compile(r"\b[A-Za-z_]\w*\b")


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


def citation_spans(source, text):
    """Return up to four AST-anchored spans for identifiers named in ``text``.

    Only bounded, parseable Python source records are considered. Locations are
    absolute source lines and remain within the supplied record. These spans
    identify syntax; they do not resolve dynamic dispatch or prove execution.
    """
    if not isinstance(text, str):
        return []
    parsed = _source_tree(source)
    if parsed is None:
        return []
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
    for name, nodes in definitions.items():
        for node in nodes:
            span = _span(node, start - 1, start, end)
            if span is not None:
                fallback.append((span[0], span[1], name))
    # Prefer concrete call sites in named functions; otherwise expose the
    # mentioned rule references and exact definitions in source order.
    candidates = preferred if preferred else fallback
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
