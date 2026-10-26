"""Private, bounded generation candidates; never publication or tracking input."""

import hashlib
from itertools import islice
import os
from pathlib import Path
import time
from uuid import UUID

from . import intake
from .storage import StorageError, write_bundle


MAX_BYTES = 1024 * 1024
FILES = frozenset({"request.json", "evidence.json", "context.json", "receipt.json", "receipt.tmp",
                   "candidate-1.json", "candidate-2.json", "attempt-1.json", "attempt-2.json"})


class Capture:
    def __init__(self, root, request, evidence, context):
        files = {"request.json": intake.encoded(request), "evidence.json": intake.encoded(evidence),
                 "context.json": intake.encoded(context)}
        if any(len(raw) > MAX_BYTES for raw in files.values()):
            raise StorageError("Generation diagnostic input exceeds its bound")
        self.path = write_bundle(files, root)
        self.request_digest = request["request_digest"]
        self.attempts = []
        self.finish("started")

    def _write(self, name, value):
        raw = intake.encoded(value)
        if name not in FILES or len(raw) > MAX_BYTES:
            raise StorageError("Generation diagnostic exceeds its bound")
        fd = os.open(self.path / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                     | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())

    def candidate(self, candidate, tokens, schema_digest=None):
        index = len(self.attempts) + 1
        if index > 2:
            raise StorageError("Generation diagnostic attempt limit")
        self._write(f"candidate-{index}.json", candidate)
        self.attempts.append({"index": index, "plan_digest": intake.digest(candidate),
                              "provider_schema_sha256": schema_digest,
                              "input_tokens": tokens[0] if tokens else None,
                              "output_tokens": tokens[1] if tokens else None})
        self.finish("candidate_received")

    def validation(self, issue):
        # Only closed codes and sanitized field locations, never exception text.
        from .local_provider import _safe_issue
        code, location = _safe_issue(*issue)
        self._write(f"attempt-{len(self.attempts)}.json", {"code": code, "location": location})
        self.attempts[-1].update(code=code, location=location)
        self.finish("rejected")

    def finish(self, outcome, failure_code=None):
        hashes = {}
        for name in sorted(FILES - {"receipt.json", "receipt.tmp"}):
            path = self.path / name
            if path.exists():
                if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
                    raise StorageError("Generation diagnostic file changed")
                hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        value = {"schema": "hyperreview.generation-diagnostics.v1", "request_digest": self.request_digest,
                 "outcome": outcome, "failure_code": failure_code, "attempts": self.attempts,
                 "captured_candidates": len(self.attempts),
                 "files": hashes, "updated_at": int(time.time()), "publication": False}
        self._write("receipt.tmp", value)
        os.replace(self.path / "receipt.tmp", self.path / "receipt.json")


def expire(db, root, now):
    from . import worker
    directory = worker._path(root / "diagnostics")
    if not directory.exists():
        return
    worker._private_directory(directory)
    entries = list(islice(directory.iterdir(), worker.MAX_RECEIPTS * 2 + 1))
    worker._require(len(entries) <= worker.MAX_RECEIPTS * 2)
    for entry in entries:
        worker._require(str(UUID(entry.name)) == entry.name)
        worker._private_directory(entry)
        if entry.stat().st_mtime >= now - worker.RETENTION_SECONDS:
            continue
        files = list(islice(entry.iterdir(), len(FILES) + 1))
        worker._require(len(files) <= len(FILES) and all(p.name in FILES for p in files))
        for path in files:
            worker._private_file(path)
        for path in files:
            path.unlink()
        entry.rmdir()
    for row in db.execute("SELECT job,diagnostic FROM preview_jobs WHERE diagnostic IS NOT NULL").fetchall():
        worker._require(str(UUID(row["diagnostic"])) == row["diagnostic"])
        if not worker._path(directory / row["diagnostic"]).exists():
            with db:
                db.execute("UPDATE preview_jobs SET diagnostic=NULL WHERE job=?", (row["job"],))
