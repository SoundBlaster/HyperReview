"""Bounded operator inputs and private local artifacts."""

import json
import os
import re
from pathlib import Path
from uuid import uuid4


class StorageError(Exception):
    pass


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise StorageError("Duplicate JSON fields are not accepted")
        result[key] = value
    return result


def _invalid_constant(value):
    raise StorageError("Non-finite JSON values are not accepted")


def read_json(path, max_bytes=262144):
    with Path(path).open("rb") as source:
        raw = source.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise StorageError("Local JSON input exceeds its byte limit")
    try:
        return json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
    except (ValueError, UnicodeError) as error:
        raise StorageError("Local input is not valid JSON") from error


def write_bundle(files, root):
    """Names are application constants; content never chooses output paths."""
    if not files or any(not re.fullmatch(r"[a-z][a-z0-9_.-]*", name) for name in files):
        raise StorageError("Invalid application artifact names")
    if any(type(content) is not bytes for content in files.values()):
        raise StorageError("Application artifacts must be bytes")
    root = Path(os.path.abspath(root))
    for parent in (*reversed(root.parents), root):
        if parent.is_symlink():
            raise StorageError("Output root must not traverse symlinks")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination = root / str(uuid4())
    destination.mkdir(mode=0o700)
    try:
        for name, body in files.items():
            fd = os.open(destination / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as target:
                target.write(body)
    except Exception:
        for name in files:
            (destination / name).unlink(missing_ok=True)
        destination.rmdir()
        raise
    return destination
