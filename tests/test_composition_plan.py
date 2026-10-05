import unittest

from hyperreview import intake, model_contract
from hyperreview.composition_plan import (CompositionPlanError, PLAN_SCHEMA,
                                          plan_schema, to_result)
from test_model_contract import pack, source


def request_pair():
    return model_contract.prepare_request(pack([
        source("before", "old source\n", "src/before.hc"),
        source("after", "new source\n", "src/after.hc"),
    ]))


def base_plan(request, nodes=None):
    return {
        "schema": PLAN_SCHEMA,
        "request_digest": request["request_digest"],
        "nodes": [] if nodes is None else nodes,
        "summary": "Proposed architecture composition.",
        "limitations": ["Claims are inferred from supplied source data."],
    }


def node(node_id, before_type=None, after_type=None, before_parent=None,
         after_parent=None, before_refs=None, after_refs=None, reason="Responsibility mapping."):
    return {
        "id": node_id,
        "before_type": before_type,
        "after_type": after_type,
        "before_parent": before_parent,
        "after_parent": after_parent,
        "before_refs": [] if before_refs is None else list(before_refs),
        "after_refs": [] if after_refs is None else list(after_refs),
        "reason": reason,
    }


class CompositionPlanTests(unittest.TestCase):
    def setUp(self):
        self.request = request_pair()
        self.before_ref = next(item["id"] for item in self.request["sources"]
                               if item["side"] == "before")
        self.after_ref = next(item["id"] for item in self.request["sources"]
                              if item["side"] == "after")

    def test_added_root_with_three_responsibilities_renders_deterministically(self):
        plan = base_plan(self.request, [
            node("Application", after_type="Application", after_refs=[self.after_ref]),
            node("Assessment", after_type="Assessment", after_parent="Application",
                 after_refs=[self.after_ref]),
            node("Evidence", after_type="Evidence", after_parent="Application",
                 after_refs=[self.after_ref]),
            node("Review", after_type="Review", after_parent="Application",
                 after_refs=[self.after_ref]),
        ])
        result = to_result(plan, self.request)
        self.assertEqual(result["before_hc"], "\n")
        self.assertEqual(result["after_hc"],
                         "Application\n"
                         "  Assessment\n"
                         "  Evidence\n"
                         "  Review\n")
        self.assertEqual([entry["architecture_id"] for entry in result["identity_map"]],
                         ["#Application", "#Assessment", "#Evidence", "#Review"])
        self.assertEqual(result["request_digest"], self.request["request_digest"])
        self.assertIs(model_contract.validate_result(result, self.request), result)

    def test_pair_renames_moves_removals_and_input_sibling_order(self):
        plan = base_plan(self.request, [
            node("Root", "Root", "Root", before_refs=[self.before_ref], after_refs=[self.after_ref]),
            node("Second", "OldSecond", "NewSecond", "Root", "Root",
                 [self.before_ref], [self.after_ref]),
            node("First", "OldFirst", "NewFirst", "Root", "Root",
                 [self.before_ref], [self.after_ref]),
            node("Removed", "Legacy", None, "Root", None, [self.before_ref], []),
        ])
        result = to_result(plan, self.request)
        self.assertEqual(result["before_hc"], "Root\n  OldSecond\n  OldFirst\n  Legacy\n")
        self.assertEqual(result["after_hc"], "Root\n  NewSecond\n  NewFirst\n")

    def test_compact_profile_rejects_disconnected_roots(self):
        plan = base_plan(self.request, [
            node("One", after_type="One", after_refs=[self.after_ref]),
            node("Two", after_type="Two", after_refs=[self.after_ref]),
        ])
        with self.assertRaisesRegex(CompositionPlanError, "exactly one root"):
            to_result(plan, self.request)

    def test_empty_plan_is_allowed_and_preserves_empty_hc_newline(self):
        result = to_result(base_plan(self.request), self.request)
        self.assertEqual(result["before_hc"], "\n")
        self.assertEqual(result["after_hc"], "\n")
        self.assertEqual(result["identity_map"], [])

    def test_schema_is_strict_and_binds_source_enums(self):
        schema = plan_schema(self.request)
        self.assertFalse(schema["additionalProperties"])
        node_schema = schema["properties"]["nodes"]["items"]
        self.assertNotIn("allOf", node_schema)
        self.assertEqual(node_schema["required"][:2], ["reason", "id"])
        self.assertNotIn("claims", schema["properties"])
        self.assertEqual(schema["properties"]["request_digest"]["const"],
                         self.request["request_digest"])
        refs = node_schema["properties"]
        self.assertEqual(refs["before_refs"]["items"]["enum"], [self.before_ref])
        self.assertEqual(refs["after_refs"]["items"]["enum"], [self.after_ref])

    def test_schema_explains_responsibility_and_review_context(self):
        schema = plan_schema(self.request)
        properties = schema["properties"]
        node_properties = properties["nodes"]["items"]["properties"]

        self.assertIn("responsibility", node_properties["id"]["description"])
        self.assertIn("Domain responsibility", node_properties["before_type"]["description"])
        self.assertIn("Domain responsibility", node_properties["after_type"]["description"])
        self.assertIn("not PythonFile", node_properties["before_type"]["description"])
        self.assertIn("preserve before_type", node_properties["after_type"]["description"])
        self.assertIn("Write in Russian", node_properties["reason"]["description"])
        self.assertIn("concrete task and what changed/remained",
                      node_properties["reason"]["description"])
        self.assertIn("Explain comment changes separately from code behavior",
                      node_properties["reason"]["description"])
        self.assertIn("start with the actual code/comment difference",
                      properties["summary"]["description"])
        self.assertIn("preserved responsibility and knowledge boundary",
                      properties["summary"]["description"])
        self.assertIn("missing evidence specific to this interpretation",
                      properties["limitations"]["description"])
        self.assertIn("do not repeat request boilerplate",
                      properties["limitations"]["description"])

    def test_composition_schema_keeps_canonical_result_contract_unchanged(self):
        result_schema = model_contract.result_schema()
        self.assertEqual(result_schema["title"], model_contract.RESULT_SCHEMA)
        self.assertEqual(set(result_schema["required"]), {
            "schema", "request_digest", "before_hc", "after_hc", "identity_map",
            "claims", "summary", "limitations",
        })
        self.assertEqual(set(plan_schema(self.request)["properties"]), {
            "schema", "request_digest", "nodes", "summary", "limitations",
        })

    def test_rejects_missing_refs_or_refs_from_wrong_side(self):
        cases = [
            node("A", after_type="A"),
            node("A", after_type="A", after_refs=[self.before_ref]),
        ]
        for candidate in cases:
            with self.subTest(candidate=candidate):
                with self.assertRaises(CompositionPlanError):
                    to_result(base_plan(self.request, [candidate]), self.request)

    def test_absent_side_cannot_carry_parent_or_refs(self):
        candidate = node("A", after_type="A", before_parent="A", after_refs=[self.after_ref])
        with self.assertRaisesRegex(CompositionPlanError, "Absent before node"):
            to_result(base_plan(self.request, [candidate]), self.request)
        candidate["before_parent"] = None
        candidate["before_refs"] = [self.before_ref]
        with self.assertRaisesRegex(CompositionPlanError, "Absent before node"):
            to_result(base_plan(self.request, [candidate]), self.request)

    def test_rejects_orphan_cycle_and_parent_absent_on_side(self):
        cases = [
            [node("A", after_type="A", after_parent="Missing", after_refs=[self.after_ref])],
            [node("A", after_type="A", after_parent="B", after_refs=[self.after_ref]),
             node("B", after_type="B", after_parent="A", after_refs=[self.after_ref])],
            [node("A", before_type="A", before_refs=[self.before_ref]),
             node("B", after_type="B", after_parent="A", after_refs=[self.after_ref])],
        ]
        for nodes in cases:
            with self.subTest(nodes=nodes):
                with self.assertRaises(CompositionPlanError):
                    to_result(base_plan(self.request, nodes), self.request)

    def test_rejects_embedded_dsl_and_punctuation_in_identifiers(self):
        for invalid_id, invalid_type in (("Application#App", "Application"),
                                         ("App", "Application#App"),
                                         ("App\n  Inject", "Application")):
            with self.subTest(invalid_id=invalid_id, invalid_type=invalid_type):
                candidate = node(invalid_id, after_type=invalid_type,
                                 after_refs=[self.after_ref])
                with self.assertRaises(CompositionPlanError):
                    to_result(base_plan(self.request, [candidate]), self.request)

    def test_rejects_generic_container_types_but_allows_task_names(self):
        for label in ("File", "PythonFile", "Function", "Module", "Documentation", "Comment",
                      "PYTHONFILE"):
            with self.subTest(label=label):
                candidate = node("Task", after_type=label, after_refs=[self.after_ref])
                with self.assertRaisesRegex(CompositionPlanError, "generic container"):
                    to_result(base_plan(self.request, [candidate]), self.request)

        for label in ("DocumentationGeneration", "ModuleDiscovery"):
            with self.subTest(label=label):
                candidate = node("Task", after_type=label, after_refs=[self.after_ref])
                result = to_result(base_plan(self.request, [candidate]), self.request)
                self.assertEqual(result["after_hc"], f"{label}\n")

    def test_rejects_malformed_extra_fields_wrong_digest_and_unknown_refs(self):
        valid = node("App", after_type="Application", after_refs=[self.after_ref])
        mutations = []
        extra = base_plan(self.request, [valid])
        extra["unexpected"] = "value"
        mutations.append(extra)
        bad_digest = base_plan(self.request, [valid])
        bad_digest["request_digest"] = "0" * 64
        mutations.append(bad_digest)
        bad_node = base_plan(self.request, [dict(valid, extra="not allowed")])
        mutations.append(bad_node)
        unknown = base_plan(self.request, [node("App", after_type="Application",
                                                after_refs=["src_" + "0" * 64])])
        mutations.append(unknown)
        for candidate in mutations:
            with self.subTest(candidate=candidate):
                with self.assertRaises(CompositionPlanError):
                    to_result(candidate, self.request)

    def test_rejects_depth_over_32(self):
        nodes = []
        for index in range(33):
            parent = f"N{index - 1}" if index else None
            nodes.append(node(f"N{index}", after_type="Component", after_parent=parent,
                              after_refs=[self.after_ref]))
        with self.assertRaisesRegex(CompositionPlanError, "depth 32"):
            to_result(base_plan(self.request, nodes), self.request)

    def test_canonical_result_validation_rejects_invalid_claims(self):
        plan = base_plan(self.request, [node("App", after_type="Application",
                                             after_refs=[self.after_ref])])
        plan["claims"] = [{"id": "c1", "text": "Claim", "evidence_status": "proven",
                           "architecture_ids": ["#App"], "source_refs": [self.after_ref],
                           "scope": "source", "limitations": ["uncertain"]}]
        with self.assertRaisesRegex(CompositionPlanError, "unknown top-level fields"):
            to_result(plan, self.request)

    def test_rejects_plan_larger_than_wire_limit(self):
        plan = base_plan(self.request)
        plan["claims"] = [{
            "id": f"claim{index}", "text": "x" * 4000, "evidence_status": "inferred",
            "architecture_ids": [], "source_refs": [], "scope": "x" * 2000,
            "limitations": ["x" * 2000] * 100,
        } for index in range(6)]
        with self.assertRaises(CompositionPlanError):
            to_result(plan, self.request)


if __name__ == "__main__":
    unittest.main()
