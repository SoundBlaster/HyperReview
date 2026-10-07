"""Pure SpecificationCore rule for pull-request metadata eligibility."""

from __future__ import annotations

from dataclasses import dataclass
import re
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


@dataclass(frozen=True, slots=True)
class HistoricalPullRequestEligibilityContext:
    """Metadata required to analyze a merged PR as a local historical sample."""

    requested_number: int
    requested_repository: str
    configured_author: str
    number: Any
    author: Any
    state: Any
    draft: Any
    base_repository: Any
    head_repository: Any
    merged_at: Any
    merge_commit_sha: Any


@final
class HistoricalPullRequestEligibility(Specification[HistoricalPullRequestEligibilityContext]):
    """Require a merged, same-repository PR; this rule grants no publication authority."""

    __slots__ = ()

    def __init__(self) -> None:
        super().__init__("historical_pull_request_eligibility")
        self._seal()

    def _evaluate(
        self,
        candidate: HistoricalPullRequestEligibilityContext,
        recorder: TraceRecorder | None,
    ) -> bool:
        del recorder
        return (
            candidate.number == candidate.requested_number
            and candidate.author == candidate.configured_author
            and candidate.state == "closed"
            and candidate.draft is False
            and candidate.base_repository == candidate.requested_repository
            and candidate.head_repository == candidate.requested_repository
            and type(candidate.merged_at) is str
            and bool(candidate.merged_at)
            and type(candidate.merge_commit_sha) is str
            and re.fullmatch(r"[0-9a-f]{40}", candidate.merge_commit_sha) is not None
        )
