import unittest

from specification_core import TraceRecorder

from hyperreview.intake import AUTHOR, IntakeError, eligible
from hyperreview.pr_eligibility import (
    PullRequestEligibilityContext,
    PullRequestMetadataEligibility,
)


REPOSITORY = "0al-spec/SpecGraph"
NUMBER = 761
METADATA = {
    "number": NUMBER,
    "author": AUTHOR,
    "state": "open",
    "draft": False,
    "base_repo": REPOSITORY,
    "head_repo": REPOSITORY,
    "base_sha": "a" * 40,
    "head_sha": "b" * 40,
}


def context(metadata=METADATA):
    return PullRequestEligibilityContext(
        requested_number=NUMBER,
        requested_repository=REPOSITORY,
        configured_author=AUTHOR,
        number=metadata.get("number"),
        author=metadata.get("author"),
        state=metadata.get("state"),
        draft=metadata.get("draft"),
        base_repository=metadata.get("base_repo"),
        head_repository=metadata.get("head_repo"),
    )


def previous_metadata_predicate(metadata):
    """The pre-extraction condition, retained here as a parity oracle."""
    return (
        metadata.get("number") == NUMBER
        and metadata.get("author") == AUTHOR
        and metadata.get("state") == "open"
        and metadata.get("draft") is False
        and metadata.get("base_repo") == REPOSITORY
        and metadata.get("head_repo") == REPOSITORY
    )


class PullRequestMetadataEligibilityTests(unittest.TestCase):
    def test_metadata_field_parity_table(self):
        cases = (
            ("number", 762),
            ("author", "another-author"),
            ("state", "closed"),
            ("draft", True),
            ("base_repo", "another/repository"),
            ("head_repo", "another/repository"),
        )
        specification = PullRequestMetadataEligibility()
        self.assertEqual(specification.name, "pull_request_metadata_eligibility")

        for field, rejected_value in cases:
            variants = ({**METADATA, field: rejected_value},)
            for metadata in variants:
                with self.subTest(field=field, value=rejected_value):
                    self.assertEqual(
                        specification.is_satisfied_by(context(metadata)),
                        previous_metadata_predicate(metadata),
                    )
                    self.assertFalse(specification.is_satisfied_by(context(metadata)))

        self.assertEqual(
            specification.is_satisfied_by(context()),
            previous_metadata_predicate(METADATA),
        )
        self.assertTrue(specification.is_satisfied_by(context()))

    def test_draft_keeps_identity_check(self):
        # Python considers 0 equal to False, but the intake gate requires JSON false.
        metadata = {**METADATA, "draft": 0}
        self.assertEqual(
            PullRequestMetadataEligibility().is_satisfied_by(context(metadata)),
            previous_metadata_predicate(metadata),
        )
        self.assertFalse(PullRequestMetadataEligibility().is_satisfied_by(context(metadata)))

    def test_rule_is_immutable_and_trace_contains_no_metadata(self):
        specification = PullRequestMetadataEligibility()
        with self.assertRaisesRegex(AttributeError, "immutable"):
            specification._name = "changed"

        recorder = TraceRecorder()
        specification.is_satisfied_by(context(), recorder=recorder)
        self.assertEqual([event.name for event in recorder.events], [specification.name])
        trace_text = repr(recorder.events)
        for raw_fact in (AUTHOR, REPOSITORY, str(NUMBER)):
            self.assertNotIn(raw_fact, trace_text)

    def test_intake_keeps_account_and_metadata_gate_errors(self):
        eligible(REPOSITORY, NUMBER, METADATA, AUTHOR)

        with self.assertRaisesRegex(
            IntakeError,
            "Authenticated GitHub account differs from the configured author",
        ):
            eligible(REPOSITORY, NUMBER, {**METADATA, "author": "other"}, "other")

        with self.assertRaisesRegex(
            IntakeError,
            "PR is ineligible: require configured author, same repository, open and non-draft",
        ):
            eligible(REPOSITORY, NUMBER, {**METADATA, "author": "other"}, AUTHOR)

        with self.assertRaisesRegex(IntakeError, "PR has an invalid revision identity"):
            eligible(REPOSITORY, NUMBER, {**METADATA, "head_sha": "invalid"}, AUTHOR)


if __name__ == "__main__":
    unittest.main()
