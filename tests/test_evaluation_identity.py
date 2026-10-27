import copy
import hashlib
import json
from pathlib import Path
import unittest

from hyperreview import review_evaluation as evaluation


SWIFT = """struct Panel {
    func menu() {
        model.path()
        Finder.reveal()
    }
}
"""


def source(content=SWIFT, path="Panel.swift", side="after"):
    raw = content.encode()
    return {"id": "src_" + hashlib.sha256((path + side).encode()).hexdigest(),
            "path": path, "side": side, "revision": "b" * 40,
            "line_start": 1, "line_end": len(content.splitlines()), "content": content,
            "content_sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob_sha": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def bundle(sources=None, caller="menu", target="model.path"):
    sources = [source()] if sources is None else sources
    return {"request": {"sources": sources}, "evidence": {"files": [{"sources": copy.deepcopy(sources)}]},
            "result": {"claims": [{"id": "relation-v2-calls-1", "scope": "После; source analysis",
                                   "text": caller + " → " + target,
                                   "source_refs": [s["id"] for s in sources]}]}}


def check(kind="relation", side="after"):
    return {"id": "check-001", "kind": kind, "side": side, "relation_kind": "calls",
            "from_contains": ["Panel", "menu"], "to_contains": ["path"]}


def value(data, selected=None):
    case = {"checks": [check() if selected is None else selected]}
    return evaluation.observe(case, data, "model")[1][0]["value"]


class EvaluationIdentityTests(unittest.TestCase):
    def test_short_signature_and_callback_label_preserve_unique_caller(self):
        for spelling in ("menu", "menu()", "Panel.menu", "menu Finder button"):
            with self.subTest(spelling=spelling):
                self.assertEqual(value(bundle(caller=spelling)), 1)

    def test_wrong_owner_and_compound_callers_are_not_repaired(self):
        for spelling in ("Other.menu", "menu and reveal", "menu, reveal",
                         "menu Other.reveal", "menu → reveal", "menu or handler"):
            with self.subTest(spelling=spelling):
                self.assertEqual(value(bundle(caller=spelling)), 0)

    def test_ambiguous_or_overloaded_names_decline(self):
        peer = SWIFT.replace("Panel", "Other")
        for sources in ([source(), source(peer, "Other.swift")],
                        [source(SWIFT.replace("    func menu()", "    func menu(_ x: Int) { model.path() }\n    func menu()"))]):
            with self.subTest(sources=sources):
                self.assertEqual(value(bundle(sources)), 0)

    def test_only_cited_same_side_sources_establish_identity(self):
        for mode in ("missing", "unknown", "wrong_side", "duplicate"):
            data = bundle()
            claim = data["result"]["claims"][0]
            if mode == "missing":
                claim.pop("source_refs")
            elif mode == "unknown":
                claim["source_refs"] = ["src_" + "0" * 64]
            elif mode == "wrong_side":
                data["request"]["sources"][0]["side"] = "before"
            else:
                claim["source_refs"] *= 2
            with self.subTest(mode=mode):
                self.assertEqual(value(data), 0)

    def test_partial_and_unverified_blobs_never_supply_a_namespace(self):
        for mode in ("offset", "mismatch", "missing_blob", "balanced_prefix"):
            data = bundle()
            raw = data["evidence"]["files"][0]["sources"][0]
            if mode == "offset":
                data["request"]["sources"][0]["line_start"] = 2
            elif mode == "mismatch":
                raw["git_blob_sha"] = "0" * 40
            elif mode == "missing_blob":
                raw.pop("git_blob_sha")
            else:
                # A balanced first-line excerpt is not a complete file.
                raw["git_blob_sha"] = source(SWIFT + "struct Other {}\n")["git_blob_sha"]
            with self.subTest(mode=mode):
                self.assertEqual(value(data), 0)

    def test_hidden_nested_or_nonexistent_calls_do_not_credit_the_outer_caller(self):
        for content in ("struct Panel {\n func menu() { helper() }\n func helper() { model.path() }\n}\n",
                        "struct Panel {\n func menu() {\n func nested() { model.path() }\n }\n}\n",
                        "struct Panel {\n func menu() {\n func path() {}\n }\n}\n",
                        'struct Panel {\n func menu() { print("model.path()") }\n}\n'):
            with self.subTest(content=content):
                self.assertEqual(value(bundle([source(content)])), 0)

    def test_python_async_and_nested_functions_keep_their_own_identity(self):
        content = "class Panel:\n async def menu(self):\n  self.path()\n"
        self.assertEqual(value(bundle([source(content, "panel.py")], target="self.path")), 1)
        content = "class Panel:\n def menu(self):\n  def nested():\n   self.path()\n"
        self.assertEqual(value(bundle([source(content, "panel.py")], target="self.path")), 0)

    def test_unsupported_syntax_and_languages_decline(self):
        for item in (source(SWIFT + "#if DEBUG\n#endif\n"), source(SWIFT, "panel.rs"),
                     source("class Panel:\n def menu(:\n", "panel.py")):
            self.assertEqual(value(bundle([item])), 0)

    def test_unrelated_complete_callee_file_does_not_hide_a_known_caller(self):
        callee = source("#if DEBUG\nstruct Model {\n func path() {}\n}\n#endif\n", "Model.swift")
        self.assertEqual(value(bundle([source(), callee])), 1)
        ambiguous = source("#if DEBUG\nstruct Other {\n func menu() { model.path() }\n}\n#endif\n", "Other.swift")
        self.assertEqual(value(bundle([source(), ambiguous])), 0)

    def test_exact_target_and_forbidden_edge_semantics_are_preserved(self):
        exact = {"id": "check-001", "kind": "relation_exact", "side": "after", "relation_kind": "calls",
                 "from_any": ["Panel.menu"], "to_any": ["model.path"]}
        self.assertEqual(value(bundle(), exact), 1)
        self.assertEqual(value(bundle(caller="Wrong.Panel.menu"), exact), 0)
        self.assertEqual(value(bundle(target="Other.path"), exact), 0)
        self.assertEqual(value(bundle(), check("relation_absence")), 0)
        self.assertEqual(value(bundle(), check(side="before")), 0)

    def test_normalization_is_not_applied_to_other_relation_kinds(self):
        data = bundle()
        data["result"]["claims"][0]["id"] = "relation-v2-data_flow-1"
        selected = check()
        selected["relation_kind"] = "data_flow"
        self.assertEqual(value(data, selected), 0)

    def test_versioned_corpus_fixture_is_pinned_and_executable(self):
        from hyperreview import review_corpus
        root = Path(__file__).resolve().parents[1]
        corpus = review_corpus.validate_corpus(json.loads((root / "evaluations/review-corpus-v3.json").read_text()))
        entry = next(e for e in corpus["entries"] if e["id"] == "sample-007")
        path = root / entry["fixture"]["path"]
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), entry["fixture"]["sha256"])
        fixture = json.loads(path.read_text())
        for row in fixture["cases"]:
            selected = {"id": "check-001", "kind": "relation_exact", "side": "after", "relation_kind": "calls",
                        "from_any": [row["expected_from"]], "to_any": [row["target"]]}
            with self.subTest(caller=row["caller"]):
                data = bundle([source(fixture["source"], fixture["path"])], row["caller"], row["target"])
                self.assertEqual(value(data, selected), row["expected_value"])
