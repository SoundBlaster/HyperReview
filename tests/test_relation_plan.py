import copy
import unittest

from hyperreview import relation_plan, local_provider
from hyperreview.composition_plan import CompositionPlanError, to_result
from test_composition_plan import base_plan, node, request_pair
from test_callsite_navigation import request as navigation_request


class CallEndpointTests(unittest.TestCase):
    def setUp(self):
        self.request = request_pair()
        self.ref = next(s["id"] for s in self.request["sources"] if s["side"] == "after")
        self.identities = [{"architecture_id": "#Reader", "after_role": "Reader", "before_role": None}]
        self.row = {"owner_id": "#Reader", "from": "Reader.read", "to": "snapshot",
                    "kind": "calls", "side": "after", "basis": "source_analysis",
                    "explanation": "Видимый вызов; binding цели не разрешён.", "source_refs": [self.ref]}

    def test_compound_caller_and_callee_trigger_targeted_repair(self):
        for field in ("from", "to"):
            for value in ("Store.snapshot и Store.latestID", "one and two", "one, two",
                          "one; two", "one → two", "one\ntwo", "one() or two()"):
                with self.subTest(field=field, value=value):
                    row = {**self.row, field: value}
                    with self.assertRaises(relation_plan.CallEndpointError):
                        relation_plan.to_claims([row], self.request, self.identities)
        plan = base_plan(self.request, [node("Reader", after_type="Reader", after_refs=[self.ref])])
        plan.update(relations=[{**self.row, "to": "snapshot и latestID"}], relation_summary="Вызовы чтения.")
        with self.assertRaises(CompositionPlanError) as caught:
            to_result(plan, self.request)
        self.assertEqual(local_provider._issue_for_error(caught.exception), ("call_endpoint_list", ""))
        self.assertIn("ОДНА", local_provider._ISSUE_HINTS["call_endpoint_list"])

    def test_signatures_generics_and_literal_unresolved_target_remain_valid(self):
        for target in ("snapshot", "self.snapshot", "store.latestID", "Store.read(_:until:)",
                       "Store.read<T, U>(_:, until:)", "call('a,b')", "Type.`and`", "operator()"):
            with self.subTest(target=target):
                claims = relation_plan.to_claims([{**self.row, "to": target}], self.request, self.identities)
                self.assertEqual(claims[0]["text"], f"Reader.read → {target}")
        # This is a formatting guard, not a receiver/binding verifier.
        claims = relation_plan.to_claims([{**self.row, "to": "Guessed.snapshot"}], self.request, self.identities)
        self.assertIn("Guessed.snapshot", claims[0]["text"])

    def test_separate_edges_survive_and_multi_site_reuse_is_not_a_call(self):
        rows = [self.row, {**self.row, "to": "store.latestID"}]
        self.assertEqual(len(relation_plan.to_claims(rows, self.request, self.identities)), 2)
        row = {**self.row, "kind": "reuses_rule", "to": "fresh path and saved path"}
        self.assertEqual(len(relation_plan.to_claims([row], self.request, self.identities)), 1)
        legacy = copy.deepcopy(self.row)
        legacy["to"] = "one and two"
        self.assertEqual(len(relation_plan.to_claims([legacy], self.request, self.identities, legacy=True)), 1)

    def test_literal_scope_error_is_targeted_and_does_not_validate_bindings(self):
        data = navigation_request('struct Outer {\n var body: View { Inner() }\n}\n'
                                  'struct Inner {\n var body: View { Provider() }\n}\n')
        row = {**self.row, "from": "Outer.body", "to": "Provider", "source_refs": ["caller"]}
        with self.assertRaises(relation_plan.LiteralCallerError):
            relation_plan.to_claims([row], data, self.identities)
        self.assertEqual(local_provider._issue_for_error(ValueError(
            "Literal callsite names another enclosing operation")), ("literal_caller", ""))
        self.assertEqual(len(relation_plan.to_claims([{**row, "from": "Inner.body"}], data, self.identities)), 1)

    def test_unindexed_invocation_is_retained_without_literal_caller_error(self):
        for invocation in ("Provider { 1 }", "Provider<Int>()"):
            data = navigation_request(f'struct Outer {{\n var body: View {{ {invocation} }}\n}}\n'
                                      'struct Inner {\n var body: View { Provider() }\n}\n')
            row = {**self.row, "from": "Outer.body", "to": "Provider", "source_refs": ["caller"]}
            with self.subTest(invocation=invocation):
                claims = relation_plan.to_claims([row], data, self.identities)
                self.assertEqual(claims[0]["text"], "Outer.body → Provider")


if __name__ == "__main__":
    unittest.main()
