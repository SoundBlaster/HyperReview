"""Exercise the actual provider grammar using a JSON Schema implementation."""

from copy import deepcopy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator

from hyperreview.codex_provider import _codex_schema
from hyperreview import model_contract
from test_codex_provider import make_plan, make_request
from test_model_contract import pack, source


class CodexSchemaTests(unittest.TestCase):
    def setUp(self):
        self.request = make_request(paired=True)
        self.schema = _codex_schema(self.request)
        Draft202012Validator.check_schema(self.schema)
        self.validator = Draft202012Validator(self.schema)

    def test_added_removed_and_paired_nodes_are_accepted(self):
        for absent in (None, "before", "after"):
            plan = make_plan(self.request)
            if absent:
                plan["nodes"][0].update({f"{absent}_type": None,
                                         f"{absent}_parent": None, f"{absent}_refs": []})
            with self.subTest(absent=absent):
                self.validator.validate(plan)

    def test_absent_node_cannot_keep_parent_or_same_side_refs(self):
        for side in ("before", "after"):
            for field in ("parent", "refs"):
                plan = make_plan(self.request)
                original_refs = plan["nodes"][0][f"{side}_refs"]
                plan["nodes"][0].update({f"{side}_type": None,
                                         f"{side}_parent": None, f"{side}_refs": []})
                plan["nodes"][0][f"{side}_{field}"] = "assessment" if field == "parent" else original_refs
                with self.subTest(side=side, field=field):
                    self.assertFalse(self.validator.is_valid(plan))

    def test_present_node_requires_nonempty_same_side_provenance(self):
        for side in ("before", "after"):
            for refs in ([], make_plan(self.request)["nodes"][0][
                    "after_refs" if side == "before" else "before_refs"]):
                plan = make_plan(self.request)
                plan["nodes"][0][f"{side}_refs"] = refs
                with self.subTest(side=side, refs=refs):
                    self.assertFalse(self.validator.is_valid(plan))

    def test_both_sides_absent_is_rejected_but_empty_projection_is_valid(self):
        plan = make_plan(self.request)
        for side in ("before", "after"):
            plan["nodes"][0].update({f"{side}_type": None,
                                     f"{side}_parent": None, f"{side}_refs": []})
        self.assertFalse(self.validator.is_valid(plan))
        plan["nodes"] = []
        self.validator.validate(plan)

    def test_request_without_before_sources_allows_only_added_nodes(self):
        request = make_request()
        validator = Draft202012Validator(_codex_schema(request))
        plan = make_plan(request)
        validator.validate(plan)
        for field, value in (("type", "Assessment"), ("parent", "assessment"),
                             ("refs", plan["nodes"][0]["after_refs"])):
            invalid = deepcopy(plan)
            invalid["nodes"][0][f"before_{field}"] = value
            with self.subTest(field=field):
                self.assertFalse(validator.is_valid(invalid))

    def test_each_union_branch_remains_a_strict_structured_output_object(self):
        self.assertEqual(self.schema["type"], "object")
        self.assertNotIn("anyOf", self.schema)
        for branch in self.schema["properties"]["nodes"]["items"]["anyOf"]:
            self.assertIs(branch["additionalProperties"], False)
            self.assertEqual(set(branch["required"]), set(branch["properties"]))
        self.assertNotIn("uniqueItems", str(self.schema))

    def test_before_only_grammar_and_empty_request_boundary(self):
        request = model_contract.prepare_request(pack([source("before", "old source\n", "src/old.py")]))
        schema = _codex_schema(request)
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        plan = make_plan(request)
        plan["nodes"][0]["after_type"] = None
        validator.validate(plan)
        plan["nodes"].append(make_plan(self.request)["nodes"][0])
        self.assertFalse(validator.is_valid(plan))
        with self.assertRaises(model_contract.NoEligibleSourcesError):
            model_contract.prepare_request(pack([]))

    def test_failure_class_fixture_matches_the_actual_provider_grammar(self):
        path = Path(__file__).resolve().parents[1] / "evaluations/fixtures/node-presence-v1.json"
        fixture = json.loads(path.read_text())
        refs = {side: next(s["id"] for s in self.request["sources"] if s["side"] == side)
                for side in ("before", "after")}
        for case in fixture["cases"]:
            plan = make_plan(self.request)
            for side in ("before", "after"):
                for field in ("type", "parent", "refs"):
                    value = case[f"{side}_{field}"]
                    plan["nodes"][0][f"{side}_{field}"] = [refs[v] for v in value] if field == "refs" else value
            with self.subTest(case=case["id"]):
                self.assertEqual(self.validator.is_valid(plan), case["expected_valid"])
