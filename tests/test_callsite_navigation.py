import json
import unittest

from hyperreview import callsite_navigation as navigation, local_provider


def request(text, *, suffix="swift", start=1):
    return {"sources": [{"id": "caller", "path": f"src/Consumer.{suffix}", "side": "after",
                         "content": text, "line_start": start,
                         "line_end": start + len(text.splitlines()) - 1}], "unchanged_files": [],
            "change_inventory": {"files": [{"before_path": None, "after_path": f"src/Provider.{suffix}"}]}}


class CallsiteNavigationTests(unittest.TestCase):
    def test_swift_peer_scopes_are_distinct_from_file_and_architecture_owner(self):
        text = '''struct Outer {
    let model: Model
    var body: some View { Inner() }
}
private struct Inner {
    let value: String
    var body: some View {
        Provider(value: value)
        Provider(value: value)
    }
}
'''
        hints = navigation.callsite_hints(request(text))
        self.assertEqual(hints, [{"literal_target": "Provider", "partial_index": True, "sites": [
            {"source_id": "caller", "caller": "Inner.body", "line_start": 8, "line_end": 8}]}])
        payload = json.loads(local_provider._comparison_content(request(text)))
        self.assertEqual(payload["callsite_hints"], hints)
        self.assertEqual(payload["trust"], "untrusted_source_data")
        self.assertIn("not binding", payload["callsite_hint_scope"])
        self.assertLessEqual(len(local_provider._wire_bytes(payload)), 6144)

    def test_nested_swift_type_and_multiline_method_keep_the_actual_scope(self):
        text = '''struct Outer {
    struct Inner {
        func render(
            value: String
        ) -> Output {
            Provider(value: value)
        }
    }
}
'''
        site = navigation.callsite_hints(request(text))[0]["sites"][0]
        self.assertEqual((site["caller"], site["line_start"]), ("Outer.Inner.render", 6))

    def test_swift_comments_strings_and_interpolated_braces_are_not_declarations(self):
        text = r'''/* { /* struct Fake { Provider() } */ } */
struct Inner {
    var body: View {
        Text("struct Fake { Provider() }")
        Text("\(format("{ not a scope }"))")
        // Provider()
        Provider()
    }
}
'''
        site = navigation.callsite_hints(request(text))[0]["sites"][0]
        self.assertEqual((site["caller"], site["line_start"]), ("Inner.body", 7))

    def test_unsupported_swift_and_offset_windows_decline_without_blocking(self):
        for text in ('struct Inner {\n var body: View { Provider() }\n',
                     'struct Inner {\n var body: View { Text(#"raw"#); Provider() }\n}\n',
                     'struct Inner {\n var body: View { Text("""multi"""); Provider() }\n}\n',
                     '#if FEATURE\nstruct Inner {\n var body: View { Provider() }\n}\n#endif\n',
                     '/* unclosed\nstruct Inner { var body: View { Provider() } }\n'):
            with self.subTest(text=text):
                self.assertEqual(navigation.callsite_hints(request(text)), [])
        self.assertEqual(navigation.callsite_hints(request('Provider()\n', start=8)), [])
        self.assertEqual(navigation.callsite_hints(request('Provider()\n', suffix="rs")), [])

    def test_python_adapter_uses_named_function_and_skips_unnamed_callback(self):
        text = '''class Inner:
    value = Provider()
    def render(self):
        callback = lambda: Provider()
        return Provider()
'''
        hints = navigation.callsite_hints(request(text, suffix="py"))
        self.assertEqual(hints[0]["sites"], [{"source_id": "caller", "caller": "Inner.render",
                                            "line_start": 5, "line_end": 5}])

    def test_search_words_only_select_literal_hits_not_file_to_type_bindings(self):
        self.assertEqual(navigation.callsite_hints(request("struct Consumer {}\n")), [])
        data = request("struct Inner {\n var body: View { Provider() }\n}\n")
        data["change_inventory"]["files"][0]["after_path"] = "src/Other.swift"
        self.assertEqual(navigation.callsite_hints(data), [])

    def test_distinct_callers_get_a_bounded_partial_index(self):
        text = "".join(f"struct C{n} {{\n var body: View {{ Provider() }}\n}}\n" for n in range(200))
        hints = navigation.callsite_hints(request(text))
        self.assertEqual(len(hints[0]["sites"]), 4)
        self.assertTrue(hints[0]["partial_index"])
        self.assertEqual([site["caller"] for site in hints[0]["sites"]], [f"C{n}.body" for n in range(4)])

    def test_excessive_or_unparseable_source_produces_no_hints(self):
        self.assertEqual(navigation.callsite_hints(request("x" * (navigation.MAX_BYTES + 1))), [])
        self.assertEqual(navigation.callsite_hints(request("def broken(\n", suffix="py")), [])


if __name__ == "__main__":
    unittest.main()
