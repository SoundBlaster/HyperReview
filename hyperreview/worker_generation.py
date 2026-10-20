"""Fail-closed, one-shot model-to-validated-preview worker pipeline."""

import hashlib
import os
from pathlib import Path
import re
import stat
import sys
import time
from uuid import uuid4

from . import intake, model_contract


class PreviewJobError(Exception):
    """Sanitized worker failure with a stable machine-readable code."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


_OPTION_KEYS = frozenset({
    "allow_cloud_source", "codex_executable", "codex_sha256", "compiler",
    "compiler_sha256", "model", "reasoning_effort", "timeout_seconds",
})
_HEX_64 = re.compile(r"[0-9a-f]{64}\Z")
_MAX_COMPILER_BYTES = 128 * 1024 * 1024
_FINGERPRINT_FILES = (
    "hyperreview/worker_generation.py",
    "hyperreview/worker_preview.py",
    "hyperreview/automatic_review_gate.py",
    "hyperreview/worker.py",
    "hyperreview/local_provider.py",
    "hyperreview/storage.py",
    "hyperreview/codex_provider.py",
    "hyperreview/codex_isolation.py",
    "hyperreview/egress_proxy.py",
    "hyperreview/model_contract.py",
    "hyperreview/composition_plan.py",
    "hyperreview/relation_plan.py",
    "hyperreview/relation_sheet.py",
    "hyperreview/configuration_evidence.py",
    "hyperreview/compiled_preview.py",
    "hyperreview/render.py",
    "hyperreview/intake.py",
    "hyperreview/reviewer_profile.py",
    "hyperreview/reviewer_profile.md",
)
_SPECIFICATION_CORE_COMMIT = "582a77a7e1c7f144f5809558605fc9fc822d8787"


def _fail(code):
    raise PreviewJobError(code)


def _provider_failure(error):
    """Classify known local diagnostics; never persist arbitrary error prose."""
    from .codex_provider import CodexError
    from .local_provider import _ISSUE_CODES
    if type(error) is not CodexError:
        return "generation_failed"
    message = str(error)
    known = {
        "Codex CLI timed out": "codex_timeout",
        "Codex CLI preparation timed out": "codex_timeout",
        "Codex CLI could not be started": "codex_process_start_failed",
        "Codex CLI process failed": "codex_process_failed",
        "Codex CLI exited unsuccessfully": "codex_process_exit",
        "Codex CLI output exceeds 1 MiB": "codex_output_limit",
        "Codex output exceeds 1 MiB": "codex_output_limit",
        "Codex output exceeds 1 MiB or changed while being read": "codex_output_limit_or_changed",
        "Codex output must be a regular, non-symlink file": "codex_output_file_rejected",
        "Codex output changed while being read": "codex_output_binding",
        "Codex emitted malformed JSONL events": "codex_event_format",
        "Codex emitted an unexpected event": "codex_event_rejected",
        "Codex emitted an unexpected item or tool action": "codex_action_rejected",
        "Codex final message event is malformed": "codex_event_format",
        "Codex startup diagnostic has an invalid turn sequence": "codex_event_sequence",
        "Codex item is outside its active turn": "codex_event_sequence",
        "Codex thread start is out of order": "codex_event_sequence",
        "Codex turn start is out of order": "codex_event_sequence",
        "Codex turn completion is out of order": "codex_event_sequence",
        "Codex did not complete exactly one turn": "codex_turn_incomplete",
        "Codex did not emit exactly one final message": "codex_final_message_count",
        "Codex final message is unavailable": "codex_output_missing",
        "Codex final message is not UTF-8": "codex_output_encoding",
        "Codex final message is invalid JSON": "codex_output_json",
        "Codex final message must be a JSON object": "codex_output_json",
        "Codex event message does not match its bound final output": "codex_output_binding",
        "Codex process isolation could not be prepared": "codex_isolation_prepare_failed",
        "Codex process isolation failed": "codex_isolation_failed",
        "Codex feature inventory is not UTF-8": "codex_feature_inventory_encoding",
        "Codex does not expose a supported image-tool disable feature": "codex_image_feature_missing",
        "Codex output schema exceeds 1 MiB": "codex_schema_limit",
        "Codex prompt exceeds 1 MiB": "codex_prompt_limit",
        "Codex repair prompt exceeds 1 MiB": "codex_prompt_limit",
        "Codex generation failed": "codex_generation_failed",
    }
    prefix = "Codex result failed local validation (issue codes: "
    if message.startswith(prefix) and message.endswith(")"):
        issues = message[len(prefix):-1].split(", ")
        if 1 <= len(issues) <= 2 and all(issue in _ISSUE_CODES for issue in issues):
            return "codex_plan_rejected_" + "_".join(issues)
    return known.get(message, "generation_failed")


def validate_options(options):
    """Validate the closed worker configuration without requiring macOS."""
    try:
        if type(options) is not dict or set(options) != _OPTION_KEYS:
            _fail("invalid_preview_config")
        if options["allow_cloud_source"] is not True:
            _fail("invalid_preview_config")
        for key in ("codex_executable", "compiler"):
            value = options[key]
            if (type(value) is not str or not value or len(value) > 4096
                    or any(ord(char) < 32 or ord(char) == 127 for char in value)
                    or not Path(value).is_absolute()):
                _fail("invalid_preview_config")
            configured_path = Path(value)
            if ".." in configured_path.parts or configured_path.is_symlink():
                _fail("invalid_preview_config")
        for key in ("codex_sha256", "compiler_sha256"):
            if type(options[key]) is not str or _HEX_64.fullmatch(options[key]) is None:
                _fail("invalid_preview_config")
        model = options["model"]
        if (type(model) is not str or not 1 <= len(model) <= 128
                or any(ord(char) < 32 or ord(char) == 127 for char in model)):
            _fail("invalid_preview_config")
        if options["reasoning_effort"] not in ("low", "medium", "high"):
            _fail("invalid_preview_config")
        if type(options["reasoning_effort"]) is not str:
            _fail("invalid_preview_config")
        timeout = options["timeout_seconds"]
        if type(timeout) is not int or not 30 <= timeout <= 300:
            _fail("invalid_preview_config")
        return options
    except PreviewJobError:
        raise
    except (OSError, TypeError, ValueError, OverflowError):
        _fail("invalid_preview_config")


def fingerprint(options):
    """Hash worker configuration together with the code and profiles it binds."""
    validate_options(options)
    try:
        root = Path(__file__).resolve().parent.parent
        files = {}
        for relative in _FINGERPRINT_FILES:
            path = root / relative
            if path.is_symlink() or not path.is_file():
                _fail("invalid_preview_config")
            files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        payload = {
            "schema": "hyperreview.worker-generation-fingerprint.v1",
            "specification_core_commit": _SPECIFICATION_CORE_COMMIT,
            "options": options,
            "files": files,
        }
        return hashlib.sha256(intake.encoded(payload)).hexdigest()
    except PreviewJobError:
        raise
    except (OSError, TypeError, ValueError, OverflowError, RecursionError):
        _fail("invalid_preview_config")


def _compiler_pin(path, expected, deadline):
    """Check the pinned local compiler before any source can reach a provider."""
    descriptor = None
    try:
        before = path.lstat()
        if not path.is_absolute() or stat.S_ISLNK(before.st_mode):
            _fail("invalid_preview_config")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        metadata = os.fstat(descriptor)
        if (not stat.S_ISREG(metadata.st_mode) or not metadata.st_mode & 0o111
                or metadata.st_size > _MAX_COMPILER_BYTES
                or (metadata.st_dev, metadata.st_ino) != (before.st_dev, before.st_ino)):
            _fail("invalid_preview_config")
        digest = hashlib.sha256()
        total = 0
        while True:
            if time.monotonic() >= deadline:
                _fail("compilation_failed")
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > _MAX_COMPILER_BYTES:
                _fail("invalid_preview_config")
            digest.update(chunk)
        if digest.hexdigest() != expected:
            _fail("invalid_preview_config")
    except PreviewJobError:
        raise
    except (OSError, ValueError):
        _fail("invalid_preview_config")
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _validate_native_codex(options, deadline):
    if sys.platform != "darwin":
        _fail("codex_preflight_failed")
    try:
        from .codex_provider import CodexConfig, CodexError, _resolve_executable
        from .codex_isolation import IsolationError
        resolved, actual_digest = _resolve_executable(
            options["codex_executable"], deadline, isolate_process=True)
        configured_path = Path(options["codex_executable"])
        configured = configured_path.resolve(strict=True)
        if (configured_path.is_symlink() or Path(resolved) != configured
                or actual_digest != options["codex_sha256"]):
            _fail("codex_preflight_failed")
        return CodexConfig(
            model=options["model"], reasoning_effort=options["reasoning_effort"],
            executable=str(resolved), timeout_seconds=1, allow_cloud_source=True,
            isolate_process=True,
            expected_executable_sha256=options["codex_sha256"],
        )
    except PreviewJobError:
        raise
    except (CodexError, IsolationError, OSError, TypeError, ValueError):
        _fail("codex_preflight_failed")


def run(evidence, request, options):
    """Generate and compile one preview; return bytes and never persist them."""
    validate_options(options)
    started = time.monotonic()
    deadline = started + options["timeout_seconds"]

    # Validate evidence/request binding and the local compiler pin before model use.
    try:
        model_contract.validate_request(request)
        selection = request["source_selection"]
        rebuilt = model_contract.prepare_request(
            evidence, max_source_bytes=selection["max_source_bytes"],
            include_paths=selection["include_paths"])
        if rebuilt != request:
            _fail("generation_failed")
    except PreviewJobError:
        raise
    except (model_contract.ContractError, KeyError, TypeError, ValueError):
        _fail("generation_failed")

    compiler = Path(options["compiler"])
    _compiler_pin(compiler, options["compiler_sha256"], deadline)
    codex_config = _validate_native_codex(options, deadline)
    remaining = deadline - time.monotonic()
    model_budget = min(120, int(remaining) - 1)
    if model_budget < 1:
        _fail("codex_preflight_failed")
    codex_config = codex_config.__class__(
        model=codex_config.model, reasoning_effort=codex_config.reasoning_effort,
        executable=codex_config.executable, timeout_seconds=model_budget,
        allow_cloud_source=True, isolate_process=True,
        expected_executable_sha256=options["codex_sha256"],
    )

    try:
        from .codex_provider import CodexError, generate
        generated = generate(request, codex_config)
    except Exception as error:
        # Provider diagnostics can contain request material; expose only a stable code.
        if isinstance(error, PreviewJobError):
            raise
        _fail(_provider_failure(error))
    if time.monotonic() >= deadline:
        _fail("generation_failed")

    try:
        plan = generated["plan"]
        result = generated["result"]
        raw_receipt = generated["receipt"]
        model_contract.validate_result(result, request)
        from .composition_plan import to_result
        if to_result(plan, request) != result:
            _fail("generation_failed")
        receipt = dict(raw_receipt)
        if (receipt.get("provider") != "codex"
                or receipt.get("executable_sha256") != options["codex_sha256"]
                or receipt.get("request_digest") != request["request_digest"]
                or receipt.get("result_digest") != intake.digest(result)
                or receipt.get("process_isolation", {}).get("mode") != "macos-seatbelt-v1"):
            _fail("generation_failed")
        provider_attempts = receipt.get("attempt_count")
        if type(provider_attempts) is not int or not 1 <= provider_attempts <= 2:
            _fail("generation_failed")
    except PreviewJobError:
        raise
    except Exception:
        _fail("generation_failed")

    receipt.update({"stage": "model_generated", "hypercode_validation": "not_started",
                   "tracking_status": "not_started"})
    remaining = deadline - time.monotonic()
    compiler_budget = min(120, int(remaining))
    if compiler_budget < 1:
        _fail("compilation_failed")
    try:
        from .compiled_preview import compile_preview
        compiled = compile_preview(
            request, result, compiler=compiler,
            compiler_sha256=options["compiler_sha256"], timeout_seconds=compiler_budget)
    except Exception:
        _fail("compilation_failed")
    if time.monotonic() >= deadline:
        _fail("compilation_failed")

    try:
        from .render import render_preview, render_compact_preview
        import json
        artifacts = dict(compiled["artifacts"])
        semantic_diff = json.loads(artifacts["diff.json"])
        artifacts["preview.md"] = render_preview(
            request, result, compiled["receipt"], semantic_diff)
        artifacts["preview-compact.md"] = render_compact_preview(
            request, result, compiled["receipt"], semantic_diff)
        artifacts["evidence.json"] = intake.encoded(evidence)
        artifacts["composition-plan.json"] = intake.encoded(plan)
        artifacts["generation-receipt.json"] = intake.encoded(receipt)
        artifacts["metadata.json"] = intake.encoded({
            "schema": "hyperreview.preview.v1", "stage": "projections_validated",
            "tracking_correlation_id": str(uuid4()), "tracking_status": "not_started",
            "request_digest": request["request_digest"],
            "result_digest": intake.digest(result), "delivery_mode": "preview", "attempt": 1,
        })
        allowed = {
            "before.hc", "after.hc", "before.ir.json", "after.ir.json", "diff.json",
            "result.json", "request.json", "compiler-receipt.json", "preview.md",
            "preview-compact.md", "evidence.json", "composition-plan.json",
            "generation-receipt.json", "metadata.json",
        }
        if set(artifacts) != allowed or time.monotonic() >= deadline:
            _fail("preview_render_failed")
        return {"artifacts": artifacts, "provider_attempts": provider_attempts}
    except PreviewJobError:
        raise
    except Exception:
        _fail("preview_render_failed")
