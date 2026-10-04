"""Compile and compare validated model-authored Hypercode projections."""

import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import tempfile
import threading
import time

from . import intake, model_contract


MAX_PROCESS_OUTPUT_BYTES = 1024 * 1024
MAX_DIAGNOSTICS_BYTES = 64 * 1024
MAX_COMPILER_BYTES = 128 * 1024 * 1024
_HEX_64 = re.compile(r"[0-9a-f]{64}\Z")
_IR_ID = re.compile(r"[A-Za-z][A-Za-z0-9_.-]*\Z")
_DIAGNOSTIC_CODES = frozenset(("HC1001", "HC1101"))


class PreviewError(Exception):
    """Raised when compilation, IR validation, provenance, or diff checks fail."""


class CompilerCommandError(PreviewError):
    """Sanitized compiler subprocess failure with bounded diagnostic identity."""

    def __init__(self, operation, return_code, diagnostic_codes=()):
        super().__init__("Hypercode compiler command failed")
        self.operation = operation
        self.return_code = return_code
        self.diagnostic_codes = tuple(diagnostic_codes)


def _require(condition, message):
    if not condition:
        raise PreviewError(message)


def _strict_json(raw, description):
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def reject_constant(_value):
        raise ValueError("non-finite number")

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object,
                           parse_constant=reject_constant)
    except (UnicodeError, ValueError, TypeError, RecursionError, OverflowError) as error:
        raise PreviewError(f"Compiler returned invalid {description} JSON") from error
    _require(type(value) is dict, f"Compiler {description} must be a JSON object")
    return value


def _diagnostic_codes(raw):
    """Extract only recognized stable codes from bounded compiler JSON."""
    if len(raw) > MAX_DIAGNOSTICS_BYTES:
        return ()

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def reject_constant(_value):
        raise ValueError("non-finite number")

    try:
        diagnostics = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object,
                                 parse_constant=reject_constant)
    except (UnicodeError, ValueError, TypeError, RecursionError, OverflowError):
        return ()
    if type(diagnostics) is not list or not diagnostics or len(diagnostics) > 32:
        return ()
    codes = []
    for item in diagnostics:
        if (type(item) is not dict or type(item.get("code")) is not str
                or item["code"] not in _DIAGNOSTIC_CODES
                or type(item.get("severity")) is not int or item["severity"] != 1
                or item.get("source") != "hypercode"):
            return ()
        codes.append(item["code"])
    return tuple(codes)


def _compiler_sha256(path):
    try:
        before = path.lstat()
        _require(not stat.S_ISLNK(before.st_mode) and stat.S_ISREG(before.st_mode),
                 "Compiler must be a regular, non-symlink file")
        _require(bool(before.st_mode & 0o111), "Compiler is not executable")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as source:
            opened = os.fstat(source.fileno())
            current = path.lstat()
            _require(stat.S_ISREG(opened.st_mode) and not stat.S_ISLNK(current.st_mode)
                     and (opened.st_dev, opened.st_ino) == (current.st_dev, current.st_ino),
                     "Compiler changed while it was being verified")
            digest = hashlib.sha256()
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
            return digest.hexdigest()
    except PreviewError:
        raise
    except OSError as error:
        raise PreviewError("Trusted compiler cannot be inspected") from error


def _verify_compiler(path, expected):
    _require(_compiler_sha256(path) == expected, "Trusted compiler SHA256 does not match")


def _stat_fingerprint(value):
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size,
            value.st_mtime_ns, value.st_ctime_ns)


def _copy_verified_compiler(source_path, private_path, expected, deadline):
    """Copy an operator-pinned executable from one verified descriptor."""
    try:
        initial_path_stat = source_path.lstat()
        _require(not stat.S_ISLNK(initial_path_stat.st_mode)
                 and stat.S_ISREG(initial_path_stat.st_mode),
                 "Compiler must be a regular, non-symlink file")
        _require(bool(initial_path_stat.st_mode & 0o111), "Compiler is not executable")
        descriptor = os.open(source_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except PreviewError:
        raise
    except OSError as error:
        raise PreviewError("Trusted compiler cannot be inspected") from error

    digest = hashlib.sha256()
    copied = 0
    try:
        with os.fdopen(descriptor, "rb") as source:
            opened_stat = os.fstat(source.fileno())
            expected_fingerprint = _stat_fingerprint(initial_path_stat)
            _require(stat.S_ISREG(opened_stat.st_mode)
                     and _stat_fingerprint(opened_stat) == expected_fingerprint,
                     "Compiler changed while it was being opened")
            private_fd = os.open(private_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(private_fd, "wb") as destination:
                while True:
                    _require(time.monotonic() < deadline,
                             "Compiler preview exceeded its total deadline")
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    copied += len(chunk)
                    _require(copied <= MAX_COMPILER_BYTES,
                             "Trusted compiler exceeds the 128 MiB binary limit")
                    digest.update(chunk)
                    destination.write(chunk)

            final_fd_stat = os.fstat(source.fileno())
            final_path_stat = source_path.lstat()
            _require(_stat_fingerprint(final_fd_stat) == expected_fingerprint
                     and _stat_fingerprint(final_path_stat) == expected_fingerprint
                     and not stat.S_ISLNK(final_path_stat.st_mode),
                     "Compiler changed while it was being copied")
        _require(digest.hexdigest() == expected,
                 "Trusted compiler SHA256 does not match")
        private_path.chmod(0o700)
        _verify_compiler(private_path, expected)
    except PreviewError:
        raise
    except OSError as error:
        raise PreviewError("Trusted compiler could not be copied safely") from error


def _terminate(proc, *, force=False):
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL if force else signal.SIGTERM)
        elif proc.poll() is not None:
            return
        elif force:
            proc.kill()
        else:
            proc.terminate()
    except ProcessLookupError:
        pass
    except OSError:
        try:
            proc.kill()
        except OSError:
            pass


def _run_compiler(path, args, *, workdir, deadline, expected_sha256, expected_codes=(0,)):
    _verify_compiler(path, expected_sha256)
    _require(time.monotonic() < deadline, "Compiler preview exceeded its total deadline")
    remaining = deadline - time.monotonic()
    _require(remaining > 0, "Compiler preview exceeded its total deadline")
    command = [str(path)]
    if args and args[0] == "parse":
        command.extend(("--diagnostics", "json"))
    command.extend(args)
    try:
        proc = subprocess.Popen(
            command,
            cwd=workdir,
            env={"PATH": os.defpath, "LANG": "C", "LC_ALL": "C"},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            close_fds=True,
            start_new_session=(os.name == "posix"),
        )
    except OSError as error:
        raise PreviewError("Trusted compiler could not be started") from error

    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    output_size = [0]
    output_lock = threading.Lock()
    overflow = threading.Event()
    reader_error = threading.Event()

    def drain(name, stream):
        try:
            while True:
                chunk = stream.read(65536)
                if not chunk:
                    return
                with output_lock:
                    room = MAX_PROCESS_OUTPUT_BYTES - output_size[0]
                    if room > 0:
                        buffers[name].extend(chunk[:room])
                        output_size[0] += min(room, len(chunk))
                    if len(chunk) > room:
                        overflow.set()
                if overflow.is_set():
                    _terminate(proc, force=True)
        except OSError:
            reader_error.set()
            _terminate(proc, force=True)

    readers = [
        threading.Thread(target=drain, args=("stdout", proc.stdout), daemon=True),
        threading.Thread(target=drain, args=("stderr", proc.stderr), daemon=True),
    ]
    for reader in readers:
        reader.start()
    try:
        try:
            return_code = proc.wait(timeout=max(0.001, deadline - time.monotonic()))
        except subprocess.TimeoutExpired as error:
            _terminate(proc)
            try:
                proc.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                _terminate(proc, force=True)
                proc.wait()
            raise PreviewError("Compiler preview exceeded its total deadline") from error
        for reader in readers:
            reader.join(timeout=0.5)
        if any(reader.is_alive() for reader in readers):
            _terminate(proc, force=True)
            for reader in readers:
                reader.join(timeout=0.5)
            raise PreviewError("Compiler output stream did not close")
        _require(not overflow.is_set(), "Compiler subprocess output exceeds 1 MiB")
        _require(not reader_error.is_set(), "Compiler subprocess output could not be read")
    finally:
        if proc.poll() is None:
            _terminate(proc, force=True)
            proc.wait()
        if any(reader.is_alive() for reader in readers):
            # The compiler may have exited while a child retained an output
            # pipe; kill the original process group before joining readers.
            _terminate(proc, force=True)
            for reader in readers:
                reader.join(timeout=0.5)
        for stream in (proc.stdout, proc.stderr):
            if stream is not None and not any(reader.is_alive() for reader in readers):
                stream.close()

    _verify_compiler(path, expected_sha256)
    _require(time.monotonic() < deadline, "Compiler preview exceeded its total deadline")
    if return_code not in expected_codes:
        operation = args[0] if args else "unknown"
        codes = _diagnostic_codes(bytes(buffers["stderr"])) if operation == "parse" else ()
        raise CompilerCommandError(operation, return_code, codes)
    return bytes(buffers["stdout"]), return_code


def _ir_ids(document, side):
    _require(set(document) == {"version", "context", "resolver", "documentHash", "nodes"},
             f"{side} IR has missing or unknown document fields")
    _require(document.get("version") == "hypercode.ir/v2", f"{side} IR version is unsupported")
    _require(type(document.get("context")) is dict
             and all(type(key) is str and type(value) is str
                     for key, value in document["context"].items()),
             f"{side} IR context is invalid")
    resolver = document.get("resolver")
    _require(type(resolver) is dict and set(resolver) == {"name", "version"}
             and all(type(value) is str and value for value in resolver.values()),
             f"{side} IR resolver is invalid")
    _require(type(document.get("documentHash")) is str
             and _HEX_64.fullmatch(document["documentHash"]) is not None,
             f"{side} IR document hash is invalid")
    _require(type(document.get("nodes")) is list, f"{side} IR nodes must be a list")

    identifiers = set()
    stack = list(reversed(document["nodes"]))
    visited = 0
    while stack:
        node = stack.pop()
        visited += 1
        _require(visited <= 10000, f"{side} IR exceeds the node limit")
        required = {"type", "id", "hash", "properties", "children"}
        allowed = required | {"class"}
        _require(type(node) is dict and required <= set(node) <= allowed,
                 f"{side} IR node has missing or unknown fields")
        _require(type(node["type"]) is str and bool(node["type"]),
                 f"{side} IR node type is invalid")
        _require(type(node["hash"]) is str and _HEX_64.fullmatch(node["hash"]) is not None,
                 f"{side} IR node hash is invalid")
        _require(type(node["properties"]) is dict and type(node["children"]) is list,
                 f"{side} IR node properties or children are invalid")
        if "class" in node:
            _require(type(node["class"]) is str and bool(node["class"]),
                     f"{side} IR node class is invalid")
        identifier = node["id"]
        _require(type(identifier) is str and _IR_ID.fullmatch(identifier) is not None,
                 f"{side} IR contains a missing or invalid explicit ID")
        _require(identifier not in identifiers, f"{side} IR contains duplicate IDs")
        identifiers.add(identifier)
        _require(all(type(key) is str for key in node["properties"]),
                 f"{side} IR property names are invalid")
        _require(all(type(child) is dict for child in node["children"]),
                 f"{side} IR children are invalid")
        stack.extend(reversed(node["children"]))
    return identifiers


def _validate_identity_provenance(result, before_ids, after_ids):
    mapped_ids = {entry["architecture_id"][1:] for entry in result["identity_map"]}
    _require(mapped_ids == before_ids | after_ids,
             "Hypercode IR IDs do not match the model identity map")
    for entry in result["identity_map"]:
        identifier = entry["architecture_id"][1:]
        has_before_refs = bool(entry["before_refs"])
        has_after_refs = bool(entry["after_refs"])
        _require(has_before_refs == (identifier in before_ids),
                 "Before-side identity references do not match emitted IR")
        _require(has_after_refs == (identifier in after_ids),
                 "After-side identity references do not match emitted IR")


def _diff_document(raw):
    document = _strict_json(raw, "diff")
    _require(set(document) == {"version", "changes"}
             and document.get("version") == "hypercode.diff/v1"
             and type(document.get("changes")) is list,
             "Compiler diff has an invalid schema")
    for change in document["changes"]:
        _require(type(change) is dict and {"kind", "node"} <= set(change)
                 and set(change) <= {"kind", "node", "properties"}
                 and change["kind"] in {"added", "removed", "modified", "reordered"}
                 and type(change["node"]) is str and bool(change["node"]),
                 "Compiler diff contains an invalid change")
        if "properties" in change:
            _require(type(change["properties"]) is list,
                     "Compiler diff properties must be a list")
    return document


def _write_private(path, content):
    with path.open("xb") as output:
        output.write(content)
    path.chmod(0o600)


def compile_preview(request, result, *, compiler: Path, compiler_sha256: str,
                    timeout_seconds=60):
    """Validate, compile, and diff model projections using a pinned local compiler."""
    try:
        model_contract.validate_request(request)
        model_contract.validate_result(result, request)
    except model_contract.ContractError as error:
        raise PreviewError("Preview request or result failed local contract validation") from error

    _require(isinstance(compiler, Path) and compiler.is_absolute(),
             "Compiler path must be an absolute pathlib.Path")
    _require(type(compiler_sha256) is str and _HEX_64.fullmatch(compiler_sha256) is not None,
             "Compiler SHA256 must be 64 lowercase hex characters")
    _require(type(timeout_seconds) is int and 1 <= timeout_seconds <= 300,
             "timeout_seconds must be an integer from 1 through 300")
    compiler = Path(os.path.abspath(compiler))

    started = time.monotonic()
    deadline = started + timeout_seconds
    try:
        with tempfile.TemporaryDirectory(prefix="hyperreview-preview-") as temporary_directory:
            workdir = Path(temporary_directory)
            private_compiler = workdir / "hypercode-compiler"
            _copy_verified_compiler(compiler, private_compiler, compiler_sha256, deadline)
            before_hc = workdir / "before.hc"
            after_hc = workdir / "after.hc"
            before_ir_path = workdir / "before.ir.json"
            after_ir_path = workdir / "after.ir.json"
            diff_path = workdir / "diff.json"
            _write_private(before_hc, result["before_hc"].encode("utf-8"))
            _write_private(after_hc, result["after_hc"].encode("utf-8"))

            for source_path in (before_hc, after_hc):
                _run_compiler(private_compiler, ["parse", str(source_path)], workdir=workdir,
                              deadline=deadline, expected_sha256=compiler_sha256)
                _run_compiler(private_compiler, ["validate", str(source_path)], workdir=workdir,
                              deadline=deadline, expected_sha256=compiler_sha256)

            before_ir, _ = _run_compiler(
                private_compiler,
                ["emit", str(before_hc), "--format", "json", "--ir-version", "2"],
                workdir=workdir, deadline=deadline, expected_sha256=compiler_sha256,
            )
            after_ir, _ = _run_compiler(
                private_compiler,
                ["emit", str(after_hc), "--format", "json", "--ir-version", "2"],
                workdir=workdir, deadline=deadline, expected_sha256=compiler_sha256,
            )
            _require(len(before_ir) <= MAX_PROCESS_OUTPUT_BYTES
                     and len(after_ir) <= MAX_PROCESS_OUTPUT_BYTES,
                     "Compiler IR exceeds 1 MiB")
            _write_private(before_ir_path, before_ir)
            _write_private(after_ir_path, after_ir)
            before_document = _strict_json(before_ir, "before IR")
            after_document = _strict_json(after_ir, "after IR")
            before_ids = _ir_ids(before_document, "Before")
            after_ids = _ir_ids(after_document, "After")
            _validate_identity_provenance(result, before_ids, after_ids)

            diff_raw, diff_code = _run_compiler(
                private_compiler,
                ["diff", str(before_ir_path), str(after_ir_path), "--format", "json"],
                workdir=workdir, deadline=deadline, expected_sha256=compiler_sha256,
                expected_codes=(0, 1),
            )
            _require(len(diff_raw) <= MAX_PROCESS_OUTPUT_BYTES, "Compiler diff exceeds 1 MiB")
            diff = _diff_document(diff_raw)
            _require((diff_code == 0 and not diff["changes"])
                     or (diff_code == 1 and bool(diff["changes"])),
                     "Compiler diff exit status does not match its changes")
            _write_private(diff_path, diff_raw)

            _verify_compiler(private_compiler, compiler_sha256)
            receipt = {
                "stage": "projections_validated",
                "compiler_sha256": compiler_sha256,
                "request_digest": request["request_digest"],
                "result_digest": intake.digest(result),
                "before_ir_sha256": hashlib.sha256(before_ir).hexdigest(),
                "after_ir_sha256": hashlib.sha256(after_ir).hexdigest(),
                "before_document_hash": before_document["documentHash"],
                "after_document_hash": after_document["documentHash"],
                "before_resolver": before_document["resolver"],
                "after_resolver": after_document["resolver"],
                "diff_sha256": hashlib.sha256(diff_raw).hexdigest(),
                "before_ids": sorted(before_ids),
                "after_ids": sorted(after_ids),
                "change_count": len(diff["changes"]),
                "elapsed_ms": max(0, int((time.monotonic() - started) * 1000)),
                "evidence_status": "inferred",
                "tracking_status": "not_started",
            }
            artifacts = {
                "before.hc": before_hc.read_bytes(),
                "after.hc": after_hc.read_bytes(),
                "before.ir.json": before_ir,
                "after.ir.json": after_ir,
                "diff.json": diff_raw,
                "result.json": intake.encoded(result),
                "request.json": intake.encoded(request),
                "compiler-receipt.json": intake.encoded(receipt),
            }
            return {"artifacts": artifacts, "receipt": receipt}
    except PreviewError:
        raise
    except (OSError, TypeError, ValueError, OverflowError, RecursionError) as error:
        raise PreviewError("Compiled preview could not be completed") from error
