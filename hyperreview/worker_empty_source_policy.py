"""Distinguish permanent input exclusions from unavailable source evidence."""

from dataclasses import dataclass
from typing import final

from specification_core import Specification, TraceRecorder


NON_RETRYABLE_OMISSIONS = frozenset({
    "invalid_path", "operator_file", "sensitive_path", "unsupported_format",
    "symlink_or_nonregular", "input_byte_limit", "binary_content", "empty_source",
    "source_file_limit", "encoded_evidence_byte_limit", "evidence_byte_limit",
    "operator_slice", "secret_pattern", "source_byte_limit", "incomplete_pair",
    "context_byte_limit", "context_excerpted", "context_inventory_limit",
    "configuration_file_limit", "configuration_excerpt_limit",
    "configuration_environment_redacted", "configuration_secret_block",
    "configuration_secret_line", "configuration_secret_file",
    "configuration_context_omitted", "configuration_indentation_unsupported",
    "configuration_duplicate_excerpt", "configuration_omission_limit",
})


@dataclass(frozen=True, slots=True)
class EmptySourceContext:
    omission_reasons: tuple[str, ...]


@final
class NonRetryableEmptySources(Specification[EmptySourceContext]):
    """Skip only when every reason is an established selection restriction."""

    __slots__ = ()

    def __init__(self):
        super().__init__("worker_empty_source_selection_terminal")
        self._seal()

    def _evaluate(self, candidate: EmptySourceContext, recorder: TraceRecorder | None) -> bool:
        del recorder
        return bool(candidate.omission_reasons) and all(
            reason in NON_RETRYABLE_OMISSIONS for reason in candidate.omission_reasons)
