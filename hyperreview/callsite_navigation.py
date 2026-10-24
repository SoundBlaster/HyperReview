"""Optional, bounded lexical call navigation; never binding or execution proof.

Python AST and a conservative Swift brace/declaration index locate supplied
calls. Other formats and unsupported excerpts simply produce no hints. No
repository, framework or architecture-role vocabulary selects these adapters.
"""

import ast
from pathlib import PurePosixPath
import re


MAX_BYTES = 262144
MAX_SITES = 128
_NAME = r"[A-Za-z_][A-Za-z0-9_]*"
_DECL = re.compile(r"(?m)^[ \t]*(?:(?:public|private|fileprivate|internal|open|final|static|class|"
                   r"override|mutating|nonmutating|nonisolated|indirect|lazy|required|convenience)\s+)*"
                   r"(struct|class|enum|actor|protocol|extension|func|var|let)\s+(" + _NAME + r")\b")


def _swift_mask(content):
    """Hide comments/strings, preserving offsets and newlines. Decline raw/triple strings."""
    masked = list(content)

    def literal(index, depth=0):
        if depth > 32:
            raise ValueError
        start = index
        if content.startswith("//", index):
            stop = content.find("\n", index)
            return len(content) if stop < 0 else stop
        if content.startswith("/*", index):
            index, nesting = index + 2, 1
            while index < len(content) and nesting:
                if content.startswith("/*", index):
                    nesting += 1
                    index += 2
                elif content.startswith("*/", index):
                    nesting -= 1
                    index += 2
                else:
                    index += 1
            if nesting:
                raise ValueError
            return index
        if content[index] != '"':
            return start
        if content.startswith('"""', index) or (index and content[index - 1] == "#"):
            raise ValueError
        index += 1
        while index < len(content):
            if content.startswith("\\(", index):
                # Interpolated expressions can contain quoted strings and
                # braces. Skip them too; calls there are intentionally absent
                # from this partial navigation index.
                index, nesting = index + 2, 1
                while index < len(content) and nesting:
                    stop = literal(index, depth + 1)
                    if stop != index:
                        index = stop
                        continue
                    nesting += (content[index] == "(") - (content[index] == ")")
                    index += 1
                if nesting:
                    raise ValueError
            elif content[index] == "\\":
                index += 2
            elif content[index] == '"':
                return index + 1
            else:
                index += 1
        raise ValueError

    try:
        index = 0
        while index < len(content):
            stop = literal(index)
            if stop == index:
                index += 1
                continue
            masked[index:stop] = ["\n" if char == "\n" else " " for char in content[index:stop]]
            index = stop
    except (ValueError, RecursionError):
        return None
    return "".join(masked)


def _swift_sites(content, names):
    code = _swift_mask(content)
    if code is None or re.search(r"(?m)^\s*#", code):
        return []  # Conditional compilation/macros need a proper language adapter.
    stack, ends = [], {}
    for index, char in enumerate(code):
        if char == "{":
            stack.append(index)
        elif char == "}":
            if not stack:
                return []
            ends[stack.pop()] = index
    if stack:
        return []
    scopes = []
    declarations = list(_DECL.finditer(code))
    for number, declaration in enumerate(declarations):
        kind, name = declaration.groups()
        if kind == "let":
            continue
        index, parentheses = declaration.end(), 0
        limit = min(len(code), declaration.end() + 2048,
                    declarations[number + 1].start() if number + 1 < len(declarations) else len(code))
        while index < limit:
            char = code[index]
            if not parentheses and char in "=;}":
                break
            if kind == "var" and char == "\n" and not code[index:limit].lstrip().startswith("{"):
                break
            if char == "{" and not parentheses:
                scopes.append((declaration.start(), index, ends[index], kind, name))
                break
            parentheses += (char == "(") - (char == ")")
            if char == "{" and parentheses:
                index = ends[index]  # Default-argument closure, outside the function body.
            index += 1
    sites = []
    pattern = re.compile(r"(?<![\w.])(" + "|".join(re.escape(n) for n in sorted(names)) + r")\s*\(")
    for call in pattern.finditer(code):
        # Never mistake a function declaration for an invocation.
        if any(start <= call.start() <= body for start, body, _end, _kind, _name in scopes):
            continue
        enclosing = sorted((item for item in scopes if item[1] < call.start() < item[2]), key=lambda x: x[1])
        if not enclosing or enclosing[-1][3] not in ("func", "var", "let"):
            continue
        sites.append({"caller": ".".join(item[4] for item in enclosing), "target": call[1],
                      "line_start": code.count("\n", 0, call.start()) + 1,
                      "line_end": code.count("\n", 0, call.end()) + 1})
        if len(sites) == MAX_SITES:
            break
    return sites


def _python_sites(content, names):
    try:
        tree = ast.parse(content)
    except (SyntaxError, ValueError, RecursionError):
        return []
    sites, path = [], []

    class Visitor(ast.NodeVisitor):
        def visit_ClassDef(self, node):
            path.append(("class", node.name))
            for child in node.body:
                self.visit(child)
            path.pop()

        def visit_FunctionDef(self, node):
            path.append(("function", node.name))
            for child in node.body:
                self.visit(child)
            path.pop()

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Lambda(self, node):
            pass  # An unnamed callback has no stable named caller here.

        def visit_Call(self, node):
            if (path and path[-1][0] == "function" and isinstance(node.func, ast.Name)
                    and node.func.id in names and len(sites) < MAX_SITES):
                sites.append({"caller": ".".join(item[1] for item in path), "target": node.func.id,
                              "line_start": node.lineno, "line_end": node.lineno})
            self.generic_visit(node)

    try:
        Visitor().visit(tree)
    except RecursionError:
        return []
    return sites


def callsite_hints(request):
    """Locate literal invocations matching added-file stems, without inferring a binding.

    File stems only choose search words. A hit is a supplied syntactic location,
    not a claim that the new file implements it. Four targets/sites fit the
    provider's existing shared optional-payload budget.
    """
    names = {PurePosixPath(item["after_path"]).stem for item in request.get("change_inventory", {}).get("files", [])
             if item.get("before_path") is None and isinstance(item.get("after_path"), str)
             and re.fullmatch(_NAME, PurePosixPath(item["after_path"]).stem)}
    names = set(sorted(names)[:32])
    if not names:
        return []
    hits = {}
    sources = sorted(request["sources"], key=lambda s: (s["side"] != "after", s["path"], s["line_start"]))
    for source in sources:
        content = source["content"]
        if (source["line_start"] != 1 or len(content.encode()) > MAX_BYTES
                or len(content.splitlines()) != source["line_end"]):
            continue
        suffix = PurePosixPath(source["path"]).suffix
        sites = (_python_sites(content, names) if suffix == ".py" else
                 _swift_sites(content, names) if suffix == ".swift" else [])
        for site in sites:
            entries = hits.setdefault(site["target"], [])
            item = {"source_id": source["id"], **{k: v for k, v in site.items() if k != "target"}}
            if len(entries) < 4 and not any(item["source_id"] == old["source_id"]
                                           and item["caller"] == old["caller"] for old in entries):
                entries.append(item)
    return [{"literal_target": name, "sites": sites, "partial_index": True}
            for name, sites in sorted(hits.items())[:4]]
