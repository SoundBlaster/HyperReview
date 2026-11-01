import json
import unittest

from hyperreview import call_arguments, local_provider
from hyperreview.model_contract import prepare_request
from test_model_contract import pack, source


def request(before, after):
    return prepare_request(pack([source("before", before), source("after", after)]))


class CallArgumentTests(unittest.TestCase):
    def test_added_keyword_is_positive_evidence_with_exact_call_range(self):
        data = request("def run():\n    return build(root)\n",
                       "def run():\n    return build(\n        root,\n        requested_scopes=scopes,\n    )\n")
        hint, = call_arguments.hints(data)
        self.assertEqual(hint["caller"], "run")
        self.assertEqual(hint["after"]["keyword_names"], ["requested_scopes"])
        self.assertEqual((hint["after"]["line_start"], hint["after"]["line_end"]), (2, 5))
        payload = json.loads(local_provider._comparison_content(data))
        self.assertEqual(payload["call_argument_hints"], [hint])
        self.assertLessEqual(len(local_provider._wire_bytes(payload)), 6144)

    def test_unpack_remains_unknown_and_values_are_not_exported(self):
        hint, = call_arguments.hints(request("def run():\n    return build(**options)\n",
                                            "def run():\n    return build(scope='private-value', **options)\n"))
        self.assertTrue(hint["before"]["has_keyword_unpack"])
        self.assertTrue(hint["after"]["has_keyword_unpack"])
        self.assertNotIn("private-value", json.dumps(hint))

    def test_ambiguous_repeated_calls_are_not_paired(self):
        data = request("def run():\n    build()\n    build()\n",
                       "def run():\n    build(scope=x)\n    build(scope=y)\n")
        self.assertEqual(call_arguments.hints(data), [])

    def test_comments_strings_and_unsupported_or_broken_sources_give_no_false_hint(self):
        self.assertEqual(call_arguments.hints(request("def run():\n    build()\n",
            "def run():\n    # build(scope=x)\n    text = 'build(scope=x)'\n    build()\n")), [])
        self.assertEqual(call_arguments.hints(request("def run():\n    build()\n", "def broken(\n")), [])

    def test_partial_window_has_absolute_lines_and_retains_partial_label(self):
        data = request("def run():\n    build()\n", "def run():\n    build(scope=x)\n")
        for record in data["sources"]:
            record["line_start"] += 100
            record["line_end"] += 100
        hint, = call_arguments.hints(data)
        self.assertEqual(hint["after"]["line_start"], 102)
        self.assertTrue(hint["partial_index"])
