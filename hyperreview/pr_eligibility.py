"""Pure SpecificationCore rule for pull-request metadata eligibility."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, final

from specification_core import Specification, TraceRecorder


@dataclass(frozen=True, slots=True)
class PullRequestEligibilityContext:
    """The metadata facts and requested identity consumed by the rule."""

    requested_number: int
    requested_repository: str
    configured_author: str
    number: Any
    author: Any
    state: Any
    draft: Any
    base_repository: Any
    head_repository: Any


@final
class PullRequestMetadataEligibility(Specification[PullRequestEligibilityContext]):
    """Require the configured author and an open, non-draft same-repo PR."""

    __slots__ = ()

    def __init__(self) -> None:
        super().__init__("pull_request_metadata_eligibility")
        self._seal()

    def _evaluate(
        self,
        candidate: PullRequestEligibilityContext,
        recorder: TraceRecorder | None,
    ) -> bool:
        del recorder  # This rule is deterministic and has no nested evaluations.
        return (
            candidate.number == candidate.requested_number
            and candidate.author == candidate.configured_author
            and candidate.state == "open"
            and candidate.draft is False
            and candidate.base_repository == candidate.requested_repository
            and candidate.head_repository == candidate.requested_repository
        )
