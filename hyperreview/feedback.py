"""Append-only local clarity feedback for a validated HyperReview preview."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from . import intake, render
from .model_contract import ContractError
from .storage import StorageError, read_json, write_bundle
from .tracking import TrackingError, build_event


FEEDBACK_SCHEMA = "hyperreview.feedback.v1"
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_MAX_PREVIEW_BYTES = 2 * 1024 * 1024


class FeedbackError(Exception):
    """Raised when feedback cannot be bound to a validated private preview."""


def _require(condition):
    if not condition:
        raise FeedbackError("Feedback input or preview bundle is invalid")


def _safe_bundle(path):
    try:
        bundle = Path(path)
    except (TypeError, ValueError):
        raise FeedbackError("Feedback input or preview bundle is invalid") from None
    _require(bundle.is_absolute() and ".." not in bundle.parts)
    for parent in (*reversed(bundle.parents), bundle):
        _require(not parent.is_symlink())
    _require(bundle.is_dir())
    return bundle


def _read_bounded_regular(path, limit):
    _require(not Path(path).is_symlink())
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = None
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            _require(stat.S_ISREG(os.fstat(stream.fileno()).st_mode))
            raw = stream.read(limit + 1)
    except FeedbackError:
        raise
    except (OSError, ValueError, TypeError):
        raise FeedbackError("Feedback preview artifact is unavailable") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
    _require(len(raw) <= limit)
    return raw


def _parse_json_bytes(raw):
    def unique_object(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise FeedbackError("Feedback input or preview bundle is invalid")
            value[key] = item
        return value

    def reject_constant(_value):
        raise FeedbackError("Feedback input or preview bundle is invalid")

    try:
        return json.loads(raw, object_pairs_hook=unique_object, parse_constant=reject_constant)
    except FeedbackError:
        raise
    except (ValueError, UnicodeError, TypeError):
        raise FeedbackError("Feedback input or preview bundle is invalid") from None


def _validate_note(note):
    if note is None:
        return
    _require(type(note) is str and len(note) <= 2000 and "\x00" not in note)
    try:
        note.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        raise FeedbackError("Feedback input or preview bundle is invalid") from None


def _save_feedback(bundle, assessment, *, note=None, expected_preview_sha256=None, output_root):
    """Save one private feedback record without modifying the preview bundle.

    This records an operator's clarity assessment only. It is not signed user
    authentication, evidence of behavior, or authorization to publish anything.
    """
    _require(type(assessment) is str and assessment in ("ok", "not_ok"))
    _validate_note(note)
    _require(expected_preview_sha256 is None
             or (type(expected_preview_sha256) is str
                 and _HEX64.fullmatch(expected_preview_sha256) is not None))
    bundle = _safe_bundle(bundle)
    try:
        root = Path(output_root)
    except (TypeError, ValueError):
        raise FeedbackError("Feedback input or preview bundle is invalid") from None
    _require(root.is_absolute() and ".." not in root.parts
             and root != bundle and bundle not in root.parents)
    for parent in (*reversed(root.parents), root):
        _require(not parent.is_symlink())
    try:
        # Bind the output to the full compiled preview/evidence chain first.
        event = build_event(bundle)
        request = read_json(bundle / "request.json", max_bytes=262144)
        result = read_json(bundle / "result.json", max_bytes=1024 * 1024)
        compiler = read_json(bundle / "compiler-receipt.json", max_bytes=262144)
        raw_diff = _read_bounded_regular(bundle / "diff.json", 1024 * 1024)
        diff = _parse_json_bytes(raw_diff)
        raw_preview = _read_bounded_regular(bundle / "preview-compact.md", _MAX_PREVIEW_BYTES)
        _require(type(request) is dict and type(result) is dict
                 and type(compiler) is dict and type(diff) is dict)
        result_digest = intake.digest(result)
        _require(event["metadata"]["request_digest"] == request["request_digest"]
                 and event["metadata"]["result_digest"] == result_digest
                 and compiler.get("request_digest") == request["request_digest"]
                 and compiler.get("result_digest") == result_digest
                 and compiler.get("compiler_sha256") == event["metadata"]["compiler_sha256"]
                 and hashlib.sha256(raw_diff).hexdigest() == compiler.get("diff_sha256"))
        expected_preview = render.render_compact_preview(request, result, compiler, diff)
        _require(raw_preview == expected_preview)
    except FeedbackError:
        raise
    except (TrackingError, StorageError, ContractError, OSError, ValueError,
            TypeError, KeyError, OverflowError, RecursionError):
        raise FeedbackError("Feedback could not be bound to a validated preview") from None

    preview_sha256 = hashlib.sha256(raw_preview).hexdigest()
    if expected_preview_sha256 is not None:
        _require(expected_preview_sha256 == preview_sha256)
    record = {
        "schema": FEEDBACK_SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "assessment": assessment,
        "note": note,
        "repository": request["repository"],
        "pr": request["pr"],
        "merge_base_sha": request["merge_base_sha"],
        "head_sha": request["head_sha"],
        "request_digest": request["request_digest"],
        "result_digest": result_digest,
        "projection_digest": intake.digest({"before_hc": result["before_hc"],
                                            "after_hc": result["after_hc"]}),
        "preview_sha256": preview_sha256,
        "prompt_version": request["prompt_version"],
        "abstraction_profile": request["abstraction_profile"],
        "render_version": render.COMPACT_RENDER_VERSION,
        "compiler_sha256": compiler["compiler_sha256"],
        "tracking_correlation_id": event["correlation_id"],
    }
    try:
        return write_bundle({"feedback.json": intake.encoded(record)}, root)
    except (StorageError, OSError, ValueError, TypeError):
        raise FeedbackError("Feedback could not be saved to the private output root") from None


def save_feedback(bundle, assessment, *, note=None, expected_preview_sha256=None, output_root):
    """Save a bound clarity assessment and normalize operational errors."""
    try:
        return _save_feedback(bundle, assessment, note=note,
                              expected_preview_sha256=expected_preview_sha256,
                              output_root=output_root)
    except FeedbackError:
        raise
    except (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError):
        raise FeedbackError("Feedback could not be saved for this preview") from None
