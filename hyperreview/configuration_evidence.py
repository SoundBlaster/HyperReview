"""Bounded, non-executing excerpts for reviewed declarative evidence families.

This module intentionally does not parse or execute YAML, JSON, or workflow
expressions. It keeps original line numbers while selecting small source
windows and conservatively dropping secret-bearing workflow regions.
"""

import hashlib
import json
import re


MAX_FILE_BYTES = 65536
MAX_EXCERPT_BYTES = 16384
MAX_TOTAL_BYTES = 65536
MAX_EXCERPTS_PER_SIDE = 8
MAX_SOURCE_RECORDS = 60
MAX_OMISSIONS = 256

_PATH_PATTERNS = (
    re.compile(r"\.github/workflows/[^/]+\.ya?ml\Z"),
    re.compile(r"(?:[^/]+/)*(?:specs|specifications)/.+\.ya?ml\Z"),
    re.compile(r"tools/feature_passports/[^/]+\.json\Z"),
    re.compile(r"(?:[^/]+/)*[^/]+\.spec\.ya?ml\Z"),
    re.compile(r"(?:[^/]+/)*specpm\.ya?ml\Z"),
    re.compile(r"(?:[^/]+/)*[a-zA-Z0-9_-]*decisions?[a-zA-Z0-9_-]*/[^/]+\.json\Z"),
    re.compile(r"(?:[^/]+/)*(?:Cargo\.toml|pyproject\.toml|package\.json)\Z"),
    re.compile(r"(?:[^/]+/)*(?:bindings|[^/]+\.bindings)\.(?:json|ya?ml)\Z"),
    re.compile(r"(?:[^/]+/)*[^/]+\.hcs\Z"),
)
_WORKFLOW = _PATH_PATTERNS[0]
_SECRET_KEY = re.compile(
    r"(?i)(?:password|passwd|token|secret|credential|private[_-]?key|api[_-]?key)"
)
_SECRET_KEY_LINE = re.compile(
    r"^\s*['\"]?[^:'\"]*(?:password|passwd|token|secret|credential|private[_-]?key|api[_-]?key)[^:'\"]*['\"]?\s*:",
    re.IGNORECASE,
)
_SECRET_VALUE = (
    re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----", re.IGNORECASE),
    re.compile(r"\b(?:ghp_|github_pat_)[A-Za-z0-9_]{8,}\b"),
    re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
    re.compile(r"\$\{\{\s*secrets\.", re.IGNORECASE),
    re.compile(r"(?i)['\"]?(?:password|token|secret|credential|private[_-]?key|api[_-]?key)['\"]?\s*[:=]\s*['\"][^'\"]+['\"]"),
    re.compile(r"(?i)\b(?:password|token|secret|credential|private[_-]?key|api[_-]?key)\b\s*[:=]\s*[^\s$][A-Za-z0-9_./+:-]{7,}"),
)
_WORKFLOW_FOCUS = re.compile(
    r"(?i)(?:upload-artifact|download-artifact|artifact|deploy|release|build|install"
    r"|setup-python|setup-node|pip(?:3)?\b|pytest|make\s+test|requirements|needs\s*:|"
    r"actions/(?:checkout|setup-|upload-artifact|download-artifact))"
)
_WORKFLOW_DEPLOY = re.compile(r"(?i)(?:download-artifact|^\s{2}[A-Za-z0-9_-]*deploy[A-Za-z0-9_-]*\s*:|needs\s*:)")
_WORKFLOW_BUILD = re.compile(r"(?i)(?:upload-artifact|^\s{2}build\s*:)")
_WORKFLOW_INSTALL = re.compile(r"(?i)(?:setup-python|setup-node|pip(?:3)?\b|install|pytest|requirements|make\s+test)")
_CONFIG_FOCUS = re.compile(
    r"(?i)(?:\b(?:id|name|title|spec|node|feature|passport|binding|intent|rule|test|command|path|source|version)\b)"
)


def accepts_path(path, generic_exclusion):
    """Admit reviewed semantic families, never bypassing path/operator exclusions."""
    return (type(path) is str and generic_exclusion == "unsupported_format"
            and any(pattern.fullmatch(path) is not None for pattern in _PATH_PATTERNS))


def _line_secret(line):
    return any(pattern.search(line) for pattern in _SECRET_VALUE)


def contains_sensitive_content(content):
    """Check the full verified blob before selecting ordinary context windows."""
    return _line_secret(content)


def _workflow_safe_lines(lines):
    # A recognized private-key opener may live under an innocuous YAML key or
    # inside a shell heredoc. Dropping only that line would export its body.
    if any(_SECRET_VALUE[0].search(line) for line in lines):
        return [False] * len(lines), [(number, "configuration_secret_file")
                                      for number in range(1, len(lines) + 1)]
    safe = []
    omissions = []
    env_indent = None
    secret_indent = None
    indentation_unsupported = False
    for number, line in enumerate(lines, 1):
        raw = line.rstrip("\r\n")
        prefix = raw[:len(raw) - len(raw.lstrip())]
        indent = len(prefix)
        if indentation_unsupported:
            safe.append(False)
            omissions.append((number, "configuration_indentation_unsupported"))
            continue
        if "\t" in prefix:
            safe.append(False)
            omissions.append((number, "configuration_indentation_unsupported"))
            # Indentation is what bounds env and sensitive-key blocks. Once
            # tabs make that structure ambiguous, suppress the rest of file.
            indentation_unsupported = True
            continue
        if env_indent is not None:
            if not raw.strip() or raw.lstrip().startswith("#"):
                safe.append(False)
                omissions.append((number, "configuration_environment_redacted"))
                continue
            if indent > env_indent:
                safe.append(False)
                omissions.append((number, "configuration_environment_redacted"))
                continue
            env_indent = None
        if secret_indent is not None:
            if not raw.strip() or raw.lstrip().startswith("#"):
                safe.append(False)
                omissions.append((number, "configuration_secret_block"))
                continue
            if indent > secret_indent:
                safe.append(False)
                omissions.append((number, "configuration_secret_block"))
                continue
            secret_indent = None
        env = re.match(r"^\s*(?:-\s+)?(?P<key>env|'env'|\"env\")\s*:", raw, re.IGNORECASE)
        if env:
            safe.append(False)
            omissions.append((number, "configuration_environment_redacted"))
            # GitHub Actions environment maps are nested below the key. An
            # inline value is wholly removed by excluding the key line itself.
            env_indent = env.start("key")
            continue
        if _line_secret(raw) or _SECRET_KEY_LINE.match(raw):
            safe.append(False)
            omissions.append((number, "configuration_secret_line"))
            if _SECRET_KEY_LINE.match(raw):
                secret_indent = indent
            continue
        safe.append(True)
    return safe, omissions


def _generic_safe_lines(lines):
    safe = []
    omissions = []
    # Do not return a JSON/YAML object with a potentially nested credential
    # object partly visible. A sensitive key anywhere suppresses the file.
    if any(_SECRET_KEY.search(line) or _line_secret(line) for line in lines):
        return [False] * len(lines), [(number, "configuration_secret_file")
                                      for number in range(1, len(lines) + 1)]
    for number, line in enumerate(lines, 1):
        if _line_secret(line):
            safe.append(False)
            omissions.append((number, "configuration_secret_line"))
        else:
            safe.append(True)
    return safe, omissions


def _compress_omissions(omitted_lines):
    result = []
    for line, reason in omitted_lines:
        if result and result[-1]["reason"] == reason and result[-1]["line_end"] + 1 == line:
            result[-1]["line_end"] = line
        else:
            result.append({"line_start": line, "line_end": line, "reason": reason})
    return result


def _ranges(lines, safe, path):
    """Return merged context windows around relevant lines, preserving order."""
    if not lines:
        return []
    if not any(safe):
        return []
    workflow = _WORKFLOW.fullmatch(path) is not None
    if not workflow and len("".join(lines).encode("utf-8")) <= MAX_EXCERPT_BYTES:
        return [(0, len(lines))]
    pattern = _WORKFLOW_FOCUS if workflow else _CONFIG_FOCUS
    selected = [index for index, line in enumerate(lines) if safe[index] and pattern.search(line)]
    if not selected:
        selected = [index for index, keep in enumerate(safe) if keep][:8]
    radius = 3 if workflow else 1
    categories = []
    if workflow:
        for matcher in (_WORKFLOW_DEPLOY, _WORKFLOW_BUILD, _WORKFLOW_INSTALL):
            categories.extend(index for index, line in enumerate(lines)
                              if safe[index] and matcher.search(line))
    priority = []
    if categories:
        deploy = [i for i, line in enumerate(lines)
                  if safe[i] and _WORKFLOW_DEPLOY.search(line)]
        build = [i for i, line in enumerate(lines)
                 if safe[i] and _WORKFLOW_BUILD.search(line)]
        install = [i for i, line in enumerate(lines)
                   if safe[i] and _WORKFLOW_INSTALL.search(line)]
        priority = deploy + build + install
        selected = list(dict.fromkeys(priority + selected))
    windows = []
    selected.sort()
    for index in selected:
        start, end = max(0, index - radius), min(len(lines), index + radius + 1)
        if windows and start <= windows[-1][1]:
            windows[-1] = (windows[-1][0], max(windows[-1][1], end))
        else:
            windows.append((start, end))
    if not workflow:
        return windows
    # Bound a merged cluster of many workflow steps into separate windows.
    split = []
    for start, end in windows:
        while end - start > 80:
            split.append((start, start + 80))
            start += 80
        split.append((start, end))
    def category(item):
        indices = range(item[0], item[1])
        if any(_WORKFLOW_DEPLOY.search(lines[i]) for i in indices):
            return 0
        if any(_WORKFLOW_BUILD.search(lines[i]) for i in indices):
            return 1
        if any(_WORKFLOW_INSTALL.search(lines[i]) for i in indices):
            return 2
        return 3

    ranked = sorted(split, key=lambda item: (category(item), item[0]))
    keep = []
    # Reserve a representative window for each deployment-stage relationship
    # before filling remaining slots from nearby relevant context.
    for matcher in (_WORKFLOW_DEPLOY, _WORKFLOW_BUILD, _WORKFLOW_INSTALL):
        match = next((item for item in split
                      if any(safe[i] and matcher.search(lines[i]) for i in range(*item))), None)
        if match is not None and match not in keep:
            keep.append(match)
    for item in ranked:
        if len(keep) >= MAX_EXCERPTS_PER_SIDE:
            break
        if item not in keep:
            keep.append(item)
    # Byte admission must use this priority order. Sorting by source position
    # here would let a large earlier build exhaust the budget before deploy.
    return keep


def source_id(revision, path, excerpt_digest):
    canonical = json.dumps([revision, path, excerpt_digest], ensure_ascii=True,
                           sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "src_" + hashlib.sha256(canonical).hexdigest()


def _excerpt_digest(excerpt):
    digest = hashlib.sha256(excerpt.encode("utf-8")).hexdigest()
    return digest


def extract(path, source, *, max_total_bytes=MAX_TOTAL_BYTES,
            max_excerpts=MAX_EXCERPTS_PER_SIDE):
    """Return safe source excerpts plus full-blob coverage metadata.

    ``source`` is the already-verified record returned by intake.source().
    Excerpt sources retain the ordinary request source shape; blob hashes and
    coverage details stay in the evidence-pack metadata.
    """
    if (not accepts_path(path, "unsupported_format") or type(source) is not dict
            or type(source.get("content")) is not str):
        raise ValueError("unsupported configuration evidence input")
    text = source["content"]
    raw_bytes = text.encode("utf-8")
    if len(raw_bytes) > MAX_FILE_BYTES or type(max_total_bytes) is not int or max_total_bytes < 0:
        return [], {"coverage": "omitted", "omissions": [{"line_start": 1, "line_end": 1,
                    "reason": "configuration_file_limit"}], "blob_sha256": source.get("content_sha256"),
                    "git_blob_sha": source.get("git_blob_sha"), "blob_bytes": source.get("content_bytes"),
                    "excerpt_source_ids": [], "line_count": max(1, text.count("\n"))}
    parts = text.split("\n")
    lines = [part + "\n" for part in parts[:-1]]
    if parts[-1]:
        lines.append(parts[-1])
    if not lines and text == "":
        return [], {"coverage": "omitted", "omissions": [{"line_start": 1, "line_end": 1,
                    "reason": "empty_source"}], "blob_sha256": source.get("content_sha256"),
                    "git_blob_sha": source.get("git_blob_sha"), "blob_bytes": source.get("content_bytes"),
                    "excerpt_source_ids": [], "line_count": 1}
    safe, omitted_lines = (_workflow_safe_lines(lines) if _WORKFLOW.fullmatch(path)
                           else _generic_safe_lines(lines))
    ranges = _ranges(lines, safe, path)
    excerpts = []
    omitted = _compress_omissions(omitted_lines)
    budget = min(MAX_EXCERPT_BYTES, max_total_bytes)
    used = 0
    for start, end in ranges:
        # Keep omission markers in the excerpt sequence as comments while
        # preserving the original line count and line-number mapping.
        output = []
        for index in range(start, end):
            if safe[index]:
                output.append(lines[index])
            else:
                output.append("# [INTAKE REDACTED; original line omitted]\n")
        excerpt = "".join(output)
        encoded_size = len(excerpt.encode("utf-8"))
        if len(excerpts) >= min(MAX_EXCERPTS_PER_SIDE, max_excerpts) or used + encoded_size > budget:
            omitted.append({"line_start": start + 1, "line_end": end,
                            "reason": "configuration_excerpt_limit"})
            continue
        excerpt_digest = _excerpt_digest(excerpt)
        excerpt_source_id = source_id(source["revision"], path, excerpt_digest)
        if any(record["source_id"] == excerpt_source_id for record in excerpts):
            omitted.append({"line_start": start + 1, "line_end": end,
                            "reason": "configuration_duplicate_excerpt"})
            continue
        record = {
            "revision": source["revision"], "path": path,
            "git_blob_sha": source["git_blob_sha"],
            "content_sha256": excerpt_digest, "content_bytes": encoded_size,
            "line_start": start + 1, "line_end": end,
            "content": excerpt, "trust": "untrusted_source_data",
            "url": source["url"], "source_id": excerpt_source_id,
        }
        excerpts.append(record)
        used += encoded_size
    excerpts.sort(key=lambda record: record["line_start"])
    included_lines = {number for record in excerpts
                      for number in range(record["line_start"], record["line_end"] + 1)}
    omitted_line_map = {line: reason for line, reason in omitted_lines}
    for omission in _compress_omissions([
            (line_number, "configuration_context_omitted")
            for line_number in range(1, len(lines) + 1)
            if line_number not in included_lines and line_number not in omitted_line_map]):
        omitted.append(omission)
    omitted.sort(key=lambda value: (value["line_start"], value["line_end"], value["reason"]))
    full = len(included_lines) == len(lines) and not omitted_lines and not omitted
    if len(omitted) > MAX_OMISSIONS:
        excerpts = []
        omitted = [{"line_start": 1, "line_end": max(1, len(lines)),
                    "reason": "configuration_omission_limit"}]
        full = False
    metadata = {
        "coverage": "complete" if full else "partial",
        "blob_sha256": source["content_sha256"],
        "git_blob_sha": source["git_blob_sha"],
        "blob_bytes": source["content_bytes"],
        "excerpt_source_ids": [record["source_id"] for record in excerpts],
        "omissions": omitted,
        "line_count": len(lines),
    }
    for record in excerpts:
        record.pop("source_id")
        record["side"] = source.get("side")
    return excerpts, metadata
