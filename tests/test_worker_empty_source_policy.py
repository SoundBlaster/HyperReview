import unittest

from hyperreview import model_contract
from hyperreview.worker_empty_source_policy import (
    EmptySourceContext, NonRetryableEmptySources, NON_RETRYABLE_OMISSIONS,
)
from test_model_contract import pack


class EmptySourcePolicyTests(unittest.TestCase):
    def test_each_known_permanent_reason_and_a_combination_are_terminal(self):
        rule = NonRetryableEmptySources()
        for reason in NON_RETRYABLE_OMISSIONS:
            with self.subTest(reason=reason):
                self.assertTrue(rule.is_satisfied_by(EmptySourceContext((reason,))))
        self.assertTrue(rule.is_satisfied_by(EmptySourceContext(tuple(sorted(NON_RETRYABLE_OMISSIONS)))))

    def test_empty_unknown_and_unavailable_reasons_are_not_terminal(self):
        rule = NonRetryableEmptySources()
        for reasons in ((), ("unknown_intake_omission",), ("future_reason",),
                        ("source_read_failure",), ("blob_integrity_failure",),
                        ("missing_tree_entry",), ("revision_mismatch",)):
            with self.subTest(reasons=reasons):
                self.assertFalse(rule.is_satisfied_by(EmptySourceContext(reasons)))

    def test_mixed_permanent_and_unavailable_reasons_keep_retry_path(self):
        rule = NonRetryableEmptySources()
        for reason in ("source_read_failure", "blob_integrity_failure", "future_reason"):
            with self.subTest(reason=reason):
                self.assertFalse(rule.is_satisfied_by(EmptySourceContext(("input_byte_limit", reason))))


class EmptySourceContractTests(unittest.TestCase):
    def test_empty_normalization_has_typed_sorted_deduplicated_reason_codes(self):
        evidence = pack(sources=[], omissions=[
            {"side": "both", "reason": "operator_file"},
            {"side": "both", "reason": "input_byte_limit"},
            {"side": "both", "reason": "operator_file"},
        ])
        with self.assertRaises(model_contract.NoEligibleSourcesError) as caught:
            model_contract.prepare_request(evidence)
        self.assertIsInstance(caught.exception, model_contract.ContractError)
        self.assertEqual(caught.exception.omission_reasons, ("input_byte_limit", "operator_file"))
        self.assertEqual(str(caught.exception), "No eligible source records remain for model analysis")

    def test_unknown_reason_is_sanitized_and_missing_reasons_remain_empty(self):
        for omissions, expected in (([], ()),
                                   ([{"side": "both", "reason": "private exception text"}],
                                    ("unknown_intake_omission",))):
            with self.subTest(omissions=omissions):
                with self.assertRaises(model_contract.NoEligibleSourcesError) as caught:
                    model_contract.prepare_request(pack(sources=[], omissions=omissions))
                self.assertEqual(caught.exception.omission_reasons, expected)
                self.assertNotIn("private exception text", str(caught.exception))

    def test_malformed_evidence_is_not_reclassified_as_an_empty_selection(self):
        evidence = pack(sources=[])
        evidence["evidence_digest"] = "0" * 64
        with self.assertRaises(model_contract.ContractError) as caught:
            model_contract.prepare_request(evidence)
        self.assertNotIsInstance(caught.exception, model_contract.NoEligibleSourcesError)
