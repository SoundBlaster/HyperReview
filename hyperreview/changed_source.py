"""Small, line-preserving windows from verified changed source blobs."""

import hashlib
import re


MAX_BLOB_BYTES = 3 * 1024 * 1024
MAX_PATCH_BYTES = 128 * 1024
MAX_HUNKS = 8
CONTEXT_LINES = 8
_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?:.*)$")


def windows(patch, before, after):
    """Validate hunk text against both blobs; return bounded paired windows.

    A patch can omit changes, so these windows are always partial evidence.
    Invalid or incomplete hunks fail closed rather than citing guessed lines.
    """
    if not isinstance(patch, str) or not patch or len(patch.encode()) > MAX_PATCH_BYTES:
        return []
    def source_lines(text):
        parts = text.split("\n")
        return [value + "\n" for value in parts[:-1]] + ([parts[-1]] if parts[-1] else [])

    old = source_lines(before["content"])
    new = source_lines(after["content"])
    lines = patch.splitlines()
    hunks = []
    index = 0
    while index < len(lines):
        match = _HUNK.fullmatch(lines[index])
        if not match:
            return []
        old_start, old_count, new_start, new_count = (
            int(match[1]), int(match[2] or 1), int(match[3]), int(match[4] or 1))
        old_pos = old_start - 1 if old_count else old_start
        new_pos = new_start - 1 if new_count else new_start
        if old_pos < 0 or new_pos < 0 or old_pos + old_count > len(old) or new_pos + new_count > len(new):
            return []
        old_seen = new_seen = 0
        index += 1
        while index < len(lines) and not lines[index].startswith("@@ "):
            line = lines[index]
            if line == r"\ No newline at end of file":
                index += 1
                continue
            if not line or line[0] not in " +-":
                return []
            text = line[1:]
            if line[0] in " -":
                if old_seen >= old_count or old[old_pos + old_seen].rstrip("\n") != text:
                    return []
                old_seen += 1
            if line[0] in " +":
                if new_seen >= new_count or new[new_pos + new_seen].rstrip("\n") != text:
                    return []
                new_seen += 1
            index += 1
        if old_seen != old_count or new_seen != new_count:
            return []
        hunks.append((old_pos, old_count, new_pos, new_count))
    result = []
    ids = set()
    for old_pos, old_count, new_pos, new_count in hunks[:MAX_HUNKS]:
        pair = []
        for record, content, pos, count in ((before, old, old_pos, old_count),
                                             (after, new, new_pos, new_count)):
            start = max(0, pos - CONTEXT_LINES)
            end = min(len(content), pos + count + CONTEXT_LINES)
            excerpt = "".join(content[start:end])
            if not excerpt:
                return []
            digest = hashlib.sha256(excerpt.encode()).hexdigest()
            identity = (record["revision"], record["path"], digest)
            if identity in ids:
                return []
            ids.add(identity)
            pair.append({**record, "content": excerpt, "content_bytes": len(excerpt.encode()),
                         "content_sha256": digest, "line_start": start + 1, "line_end": end})
        result.append(pair)
    return result
