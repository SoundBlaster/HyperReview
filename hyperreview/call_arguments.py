"""Bounded positive evidence of changed Python keyword arguments, never binding proof."""

import ast
from collections import defaultdict

MAX_BYTES = 262144
MAX_SITES = 128
MAX_NAMES = 16


def _target(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _target(node.value)
        return base + "." + node.attr if base else None
    return None


def _sites(source):
    if (not source["path"].endswith(".py") or len(source["content"].encode()) > MAX_BYTES
            or source["line_end"] - source["line_start"] + 1 != source["content"].count("\n")
            + int(not source["content"].endswith("\n"))):
        return []
    try:
        tree = ast.parse(source["content"])
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return []
    sites, scopes = [], []

    class Visitor(ast.NodeVisitor):
        def visit_ClassDef(self, node):
            scopes.append(("class", node.name))
            for statement in node.body:
                self.visit(statement)
            scopes.pop()

        def visit_FunctionDef(self, node):
            scopes.append(("function", node.name))
            for statement in node.body:
                self.visit(statement)
            scopes.pop()

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Lambda(self, node):
            pass

        def visit_Call(self, node):
            target = _target(node.func)
            if len(sites) >= MAX_SITES:
                return
            if scopes and scopes[-1][0] == "function" and target:
                names = sorted(keyword.arg for keyword in node.keywords if keyword.arg is not None)
                sites.append({"caller": ".".join(item[1] for item in scopes), "target": target,
                              "source_id": source["id"],
                              "line_start": source["line_start"] + node.lineno - 1,
                              "line_end": source["line_start"] + node.end_lineno - 1,
                              "keyword_names": names[:MAX_NAMES],
                              "names_complete": len(names) <= MAX_NAMES,
                              "has_keyword_unpack": any(k.arg is None for k in node.keywords)})
            self.generic_visit(node)

    try:
        Visitor().visit(tree)
    except (RecursionError, MemoryError):
        return []
    return sites if len(sites) < MAX_SITES else []


def hints(request):
    """Pair only unique literal caller/target occurrences in the same path.

    Keyword names are positive source facts. No hint establishes callee binding,
    runtime values, parameter defaults, or absence through **kwargs.
    """
    groups = defaultdict(lambda: {"before": [], "after": []})
    for source in request["sources"]:
        for site in _sites(source):
            groups[(source["path"], site["caller"], site["target"])][source["side"]].append(site)
    result = []
    for key, sides in sorted(groups.items()):
        if len(sides["before"]) != 1 or len(sides["after"]) != 1:
            continue
        before, after = sides["before"][0], sides["after"][0]
        if before["keyword_names"] == after["keyword_names"]:
            continue
        result.append({"path": key[0], "caller": key[1], "literal_target": key[2],
                       "before": before, "after": after, "partial_index": True})
        if len(result) == 4:
            break
    return result
