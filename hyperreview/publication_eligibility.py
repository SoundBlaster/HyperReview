"""Metadata policy for delivering an already completed live review."""

from specification_core import Specification

from .pr_eligibility import PullRequestEligibilityContext


class CompletedReviewPublicationEligibility(Specification[PullRequestEligibilityContext]):
    """Closing a PR does not revoke delivery of its revision-bound report."""

    __slots__ = ()

    def __init__(self):
        super().__init__("completed_review_publication_eligibility")
        self._seal()

    def _evaluate(self, candidate, recorder):
        del recorder
        return (candidate.number == candidate.requested_number
                and candidate.author == candidate.configured_author
                and candidate.state in ("open", "closed")
                and candidate.draft is False
                and candidate.base_repository == candidate.requested_repository
                and candidate.head_repository == candidate.requested_repository)
