"""Conservative caller spelling recovery for evaluation, not call binding.

Only cited complete Python/Swift files can qualify an abbreviated caller. The
callee stays literal, and a matching invocation must occur in that named scope.
Ambiguity or unsupported syntax produces no additional witness.
"""

import ast
import hashlib
from pathlib import PurePosixPath
import re
import unicodedata

from . import callsite_navigation


_NAME = r"[A-Za-z_][A-Za-z0-9_]*"
_PATH = _NAME + r"(?:\." + _NAME + r")*"
_CALLER = re.compile(r"(" + _PATH + r")(?:\([^()\n]*\))?"
                     r"(?:\s+(?:[A-Za-z]+\s+){0,2}(?:button|closure|callback|handler|action))?\Z")
_TARGET = re.compile(r"(" + _PATH + r")(?:\([^()\n]*\))?\Z")
_COMPOUND = re.compile(r"\b(?:and|or|и|или)\b", re.IGNORECASE)
_MAX_DECLARATIONS = 256


def _swift_declarations(content):
    indexed = callsite_navigation._swift_scopes(content)
    if indexed is None:
        return None
    code, scopes = indexed
    if len(scopes) > _MAX_DECLARATIONS:
        return None
    records = []
    for scope in scopes:
        if scope[3] not in ("func", "var"):
            continue
        parents = sorted((s for s in scopes if s[1] < scope[1] < s[2]), key=lambda s: s[1])
        records.append((".".join(s[4] for s in parents + [scope]), scope))
    return code, scopes, records


def _swift_invokes(indexed, scope, target):
    code, scopes, _records = indexed
    pattern = re.compile(r"(?<!\w)" + re.escape(target) + r"\s*\(")
    for call in pattern.finditer(code):
        if any(s[0] <= call.start() <= s[1] for s in scopes):
            continue  # A declaration/default argument is not a body invocation.
        enclosing = [s for s in scopes if s[3] in ("func", "var") and s[1] < call.start() < s[2]]
        if enclosing and max(enclosing, key=lambda s: s[1]) == scope:
            return True
    return False


def _python_declarations(content):
    records, path, owners = [], [], []

    class Visitor(ast.NodeVisitor):
        def visit_ClassDef(self, node):
            path.append(node.name)
            owners.append(None)
            for child in node.body:
                self.visit(child)
            owners.pop()
            path.pop()

        def visit_FunctionDef(self, node):
            path.append(node.name)
            record = (".".join(path), set())
            records.append(record)
            if len(records) > _MAX_DECLARATIONS:
                raise ValueError
            owners.append(record)
            for child in node.body:
                self.visit(child)
            owners.pop()
            path.pop()

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Lambda(self, node):
            pass  # Do not assign an unnamed lambda's calls to its outer owner.

        def visit_Call(self, node):
            if owners and owners[-1] is not None:
                name = node.func.id if isinstance(node.func, ast.Name) else \
                    node.func.attr if isinstance(node.func, ast.Attribute) else None
                if name is not None:
                    owners[-1][1].add(name)
            self.generic_visit(node)

    try:
        Visitor().visit(ast.parse(content))
    except (SyntaxError, ValueError, RecursionError):
        return None
    return records


class CallerIdentities:
    """Per-observation cache; neither files nor reviewer results are rewritten."""

    def __init__(self, request, evidence):
        self.sources = {}
        self.cache = {}
        self.blobs = {}
        for source in request.get("sources", []):
            if type(source) is dict and type(source.get("id")) is str:
                self.sources.setdefault(source["id"], []).append(source)
        for item in evidence.get("files", []):
            for source in item.get("sources", []):
                key = tuple(source.get(k) for k in ("side", "path", "revision", "content_sha256"))
                blob = source.get("git_blob_sha")
                if all(type(v) is str for v in key) and type(blob) is str:
                    self.blobs.setdefault(key, set()).add(blob)

    def _complete(self, source):
        content = source.get("content")
        if (type(content) is not str or any(type(source.get(k)) is not str
                                           for k in ("side", "path", "revision", "content_sha256"))
                or type(source.get("line_start")) is not int or source["line_start"] != 1
                or type(source.get("line_end")) is not int or len(content.splitlines()) != source["line_end"]):
            return False
        raw = content.encode()
        if len(raw) > callsite_navigation.MAX_BYTES or hashlib.sha256(raw).hexdigest() != source.get("content_sha256"):
            return False
        blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        key = tuple(source.get(k) for k in ("side", "path", "revision", "content_sha256"))
        return self.blobs.get(key) == {blob}

    def resolve(self, endpoint, target, claim, side):
        caller = _CALLER.fullmatch(endpoint)
        callee = _TARGET.fullmatch(target)
        if caller is None or callee is None or _COMPOUND.search(endpoint):
            return None
        refs = claim.get("source_refs")
        if (type(refs) is not list or not 1 <= len(refs) <= 8
                or any(type(ref) is not str for ref in refs) or len(set(refs)) != len(refs)):
            return None
        matches = []
        for ref in refs:
            sources = self.sources.get(ref, [])
            if len(sources) != 1 or sources[0].get("side") != side:
                return None
            source = sources[0]
            if type(source.get("path")) is not str:
                return None
            suffix = PurePosixPath(source["path"]).suffix
            if suffix not in (".swift", ".py"):
                continue
            if not self._complete(source):
                return None
            content = source["content"]
            # A cited callee file need not parse to identify a caller declared
            # elsewhere. Skip it only when the complete bytes cannot contain
            # that literal name, including Python's identifier normalization.
            name = caller[1].split(".")[-1]
            if re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)",
                         unicodedata.normalize("NFKC", content)) is None:
                continue
            if ref not in self.cache:
                self.cache[ref] = _swift_declarations(content) if suffix == ".swift" else _python_declarations(content)
            indexed = self.cache[ref]
            if indexed is None:
                return None
            records = indexed[2] if suffix == ".swift" else indexed
            for name, scope in records:
                if name == caller[1] or name.endswith("." + caller[1]):
                    invokes = _swift_invokes(indexed, scope, callee[1].split(".")[-1]) \
                        if suffix == ".swift" else callee[1].split(".")[-1] in scope
                    matches.append((name, invokes))
        # Count declarations, not just distinct names: overloads/repeated
        # owners cannot be disambiguated by this lexical index.
        return matches[0][0] if len(matches) == 1 and matches[0][1] else None
