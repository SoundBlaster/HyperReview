import json
import unittest
from unittest.mock import patch

from hyperreview import local_provider, render, source_analysis


def source(content, *, path="src/worker.rs", side="after", start=1, identifier="source"):
    return {"id": identifier, "path": path, "side": side, "content": content,
            "line_start": start, "line_end": start + len(content.splitlines()) - 1}


class SourceNavigationTests(unittest.TestCase):
    def test_literal_paths_are_positive_and_decline_ambiguous_or_unknown_syntax(self):
        record = source("Application\n  SharedLayer\n    Scan\n", path="current.hc")
        self.assertEqual(source_analysis.literal_authored_paths(record)["Scan"],
                         ("Application", "SharedLayer", "Scan"))
        for text in ("Application\n  Scan\n  Scan\n", "Application\n\tScan\n",
                     "Application\n  Scan {\n", "Application\nOtherRoot\n"):
            with self.subTest(text=text):
                self.assertNotIn("Scan", source_analysis.literal_authored_paths(
                    source(text, path="current.hc")))
        self.assertEqual(source_analysis.literal_authored_paths(
            source("SharedLayer\n  Scan\n", path="current.hc", start=20)), {})

    def test_cited_authored_owner_cannot_be_removed_by_plan_repair(self):
        from test_composition_plan import base_plan, node
        from test_model_contract import pack, source as evidence_source
        from hyperreview import composition_plan, model_contract

        request = model_contract.prepare_request(pack([evidence_source(
            "after", "Application\n  SharedLayer\n    Scan\n", "current.hc")]))
        ref = request["sources"][0]["id"]
        plan = base_plan(request, [node("app", after_type="Application", after_refs=[ref]),
                                   node("scan", after_type="Scan", after_parent="app", after_refs=[ref])])
        with self.assertRaisesRegex(composition_plan.CompositionPlanError, "Authored containment") as caught:
            composition_plan.to_result(plan, request)
        self.assertEqual(local_provider._issue_for_error(caught.exception),
                         ("authored_parent", " at nodes[1].after_parent"))
        plan["nodes"].insert(1, node("shared", after_type="SharedLayer", after_parent="app", after_refs=[ref]))
        plan["nodes"][2]["after_parent"] = "shared"
        self.assertEqual(composition_plan.to_result(plan, request)["after_hc"],
                         "Application\n  SharedLayer\n    Scan\n")
        # A bounded review may choose an authored subsystem as its root.
        plan["nodes"].pop(0)
        plan["nodes"][0]["after_parent"] = None
        self.assertEqual(composition_plan.to_result(plan, request)["after_hc"], "SharedLayer\n  Scan\n")

    def test_conflicting_cited_maps_do_not_establish_one_authoritative_path(self):
        from test_composition_plan import base_plan, node
        from test_model_contract import pack, source as evidence_source
        from hyperreview import composition_plan, model_contract

        request = model_contract.prepare_request(pack([
            evidence_source("after", "Application\n  SharedLayer\n    Scan\n", "current.hc"),
            evidence_source("after", "Application\n  Scan\n", "target.hc")]))
        refs = [record["id"] for record in request["sources"]]
        plan = base_plan(request, [node("app", after_type="Application", after_refs=refs),
                                   node("scan", after_type="Scan", after_parent="app", after_refs=refs)])
        self.assertEqual(composition_plan.to_result(plan, request)["after_hc"], "Application\n  Scan\n")

    def test_authored_role_on_both_sides_is_indexed_near_added_shared_owner(self):
        before = "Application\n  SharedRuntime\n" + "    OtherRole\n" * 60 + "    PluginScanning\n"
        after = before.replace("    PluginScanning", "    SharedAccess\n      RootAnchor\n    PluginScanning")
        request = {"sources": [source(before, path="maps/current.hc", side="before", identifier="old"),
                               source(after, path="maps/current.hc", identifier="new")], "unchanged_files": []}
        hints = list(source_analysis.authored_map_hints(request))
        self.assertEqual(len(hints), 2)
        self.assertIn("63:     PluginScanning", hints[0]["declarations"])
        self.assertIn("65:     PluginScanning", hints[1]["declarations"])
        self.assertTrue(all(hint["partial_index"] for hint in hints))
        content = json.loads(local_provider._comparison_content(request))
        self.assertEqual(content["trust"], "untrusted_source_data")
        self.assertEqual(content["authored_map_hints"], hints)
        self.assertLessEqual(len(local_provider._wire_bytes(content)), 6144)

    def test_authored_index_keeps_scope_and_rejects_ambiguous_records(self):
        request = {"sources": [source("Role\n", path="current.hc"),
                               source("Role\n", path="target.hc")]}
        self.assertEqual([item["path"] for item in source_analysis.authored_map_hints(request)],
                         ["current.hc", "target.hc"])
        request["sources"].append(source("Role\n", path="current.hc"))
        self.assertEqual([item["path"] for item in source_analysis.authored_map_hints(request)],
                         ["target.hc"])

    def test_index_does_not_interpret_comments_or_hcs_as_node_declarations(self):
        request = {"sources": [source("// HiddenRole\nRole.extra#instance\n", path="map.hc"),
                               source("HiddenRole:\n", path="map.hcs")]}
        hints = list(source_analysis.authored_map_hints(request))
        self.assertEqual(len(hints), 1)
        self.assertEqual(hints[0]["declarations"], ["2: Role.extra#instance"])

    def test_large_map_uses_a_bounded_index_without_quadratic_diff_matching(self):
        content = "Application\n" + "  RepeatedRole\n" * 1024
        request = {"sources": [source(content, path="map.hc", side="before"),
                               source(content + "  NewRole\n", path="map.hc")]}
        with patch.object(source_analysis.difflib, "SequenceMatcher", side_effect=AssertionError):
            hints = list(source_analysis.authored_map_hints(request))
        self.assertEqual(len(hints), 2)
        self.assertTrue(all(len(item["declarations"]) <= 24 for item in hints))

    def test_code_literals_locate_wiring_in_supplied_absolute_lines(self):
        record = source("fn run() {\n  let filesystem = ScopedFilesystem::open(root)?;\n"
                        "  let scope = Scope::new(&filesystem)?;\n"
                        "  scan_with_candidate_access(&filesystem, scope);\n}\n", start=101)
        spans = source_analysis.citation_spans(record, "ScopedFilesystem / scan_with_candidate_access")
        self.assertEqual(spans, [{"label": "ScopedFilesystem, scan_with_candidate_access",
                                  "line_start": 101, "line_end": 105}])

    def test_literal_navigation_is_platform_neutral_and_does_not_match_substrings(self):
        for path in ("src/worker.rs", "Sources/Worker.swift", "src/worker.ts", "src/worker.c"):
            with self.subTest(path=path):
                record = source("// SharedAccess\nlet OtherSharedAccess = 0;\n", path=path)
                self.assertEqual(source_analysis.citation_spans(record, "SharedAccess"), [])
                record = source("let access = SharedAccess();\n", path=path, start=50)
                self.assertEqual(source_analysis.citation_spans(record, "SharedAccess")[0]["line_start"], 50)

    def test_multiline_call_navigation_keeps_the_shared_object_argument(self):
        record = source("invoke_shared(\n    root,\n    options,\n    control,\n"
                        "    &filesystem,\n    observer,\n);\n", start=137)
        spans = source_analysis.citation_spans(record, "invoke_shared")
        self.assertEqual((spans[0]["line_start"], spans[0]["line_end"]), (137, 143))
        record = source("fn use_scope() {\n    Scope::new(&filesystem);\n}\n")
        self.assertTrue(source_analysis.citation_spans(record, "Scope::new"))

    def test_early_argument_match_cannot_shrink_a_multiline_call_window(self):
        record = source("invoke_shared(\n    SharedAccess::default(),\n    root,\n"
                        "    options,\n    control,\n    &filesystem,\n    observer,\n);\n", start=137)
        spans = source_analysis.citation_spans(record, "invoke_shared SharedAccess")
        self.assertEqual(len(spans), 1)
        self.assertEqual((spans[0]["line_start"], spans[0]["line_end"]), (137, 144))

    def test_lowercase_dotted_capability_is_a_complete_declarative_anchor(self):
        record = source("requires:\n  - id: product.current.scan\n    optional: false\n"
                        "  - id: product.current.scanner\n    optional: true\n",
                        path="specs/scanner.spec.yaml", start=20)
        spans = source_analysis.citation_spans(record, "product.current.scan")
        self.assertEqual(spans, [{"label": "product.current.scan", "line_start": 21, "line_end": 22}])

    def test_literal_ranges_are_bounded_and_unmatched_sources_keep_fallback(self):
        record = source("\n".join("call_shared();" for _ in range(100)))
        spans = source_analysis.citation_spans(record, "call_shared")
        self.assertLessEqual(len(spans), 4)
        self.assertTrue(all(item["line_end"] - item["line_start"] < 16 for item in spans))
        self.assertEqual(source_analysis.citation_spans(record, "unrelated_operation"), [])
        record["line_end"] += 1
        self.assertEqual(source_analysis.citation_spans(record, "call_shared"), [])

    def test_omission_summary_groups_duplicates_but_keeps_counts_sides_and_reasons(self):
        request = {"omissions": [
            {"path": "workflow.yml", "side": "before", "reason": "byte_limit"},
            {"path": "workflow.yml", "side": "after", "reason": "byte_limit"},
            {"path": "workflow.yml", "side": "after", "reason": "byte_limit"},
            {"path": "workflow.yml", "side": "after", "reason": "partial_context"},
            {"path": None, "side": "after", "reason": "hidden"}]}
        original = json.dumps(request)
        lines = render._omission_summary(request)
        self.assertEqual(len(lines), 2)
        self.assertIn("до: 1", lines[0])
        self.assertIn("после: 2", lines[0])
        self.assertIn("partial", lines[0])
        self.assertIn("путь скрыт политикой", lines[1])
        self.assertEqual(json.dumps(request), original)

    def test_configuration_coverage_merges_only_equal_displayed_ranges(self):
        record = {"path": "workflow.yml", "coverage": "partial", "source_ids": ["old"],
                  "side": "before", "omissions": [{"line_start": 2, "line_end": 5, "reason": "limit"}]}
        after = {**record, "side": "after", "source_ids": ["new"]}
        request = {"configuration_coverage": [record, after]}
        self.assertEqual(len(render._configuration_coverage(request)), 1)
        self.assertIn("before / after", render._configuration_coverage(request)[0])
        after["omissions"] = [{"line_start": 3, "line_end": 5, "reason": "limit"}]
        self.assertEqual(len(render._configuration_coverage(request)), 2)


if __name__ == "__main__":
    unittest.main()
