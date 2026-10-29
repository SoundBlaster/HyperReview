import unittest

from hyperreview import changed_source, intake, model_contract
from test_intake import BASE, HEAD, REPO, FakeGitHub, blob


class LargeModifiedFile(FakeGitHub):
    def __init__(self, *, patch=None, corrupt=False, prefix_count=22000):
        super().__init__()
        self.old = (b"padding line\n" * prefix_count) + b"old_call()\n" + (b"padding line\n" * 100)
        self.new = self.old.replace(b"old_call()\n", b"new_call()\n")
        self.old_sha, self.old_blob = blob(self.old)
        self.new_sha, self.new_blob = blob(self.new)
        line = prefix_count + 1
        self.patch = patch if patch is not None else f"@@ -{line} +{line} @@\n-old_call()\n+new_call()"
        self.corrupt = corrupt

    def get(self, endpoint, query="."):
        if "/compare/" in endpoint and ".patch" in query:
            return [self.patch]
        if "/git/trees/" in endpoint:
            raw, sha = (self.old, self.old_sha) if BASE in endpoint else (self.new, self.new_sha)
            return {"truncated": False, "tree": [{"path": "app.py", "mode": "100644",
                    "type": "blob", "sha": sha, "size": len(raw)}]}
        if "/git/blobs/" in endpoint:
            return self.old_blob if endpoint.endswith(self.old_sha) else (
                self.old_blob if self.corrupt else self.new_blob)
        return super().get(endpoint, query)


class ChangedSourceTests(unittest.TestCase):
    def test_large_modified_file_keeps_verified_paired_windows_and_partial_marker(self):
        pack = intake.collect(REPO, 761, LargeModifiedFile())
        item = next(item for item in pack["files"] if item["after_path"] == "app.py")
        self.assertEqual([s["side"] for s in item["sources"]], ["before", "after"])
        self.assertEqual(item["sources"][0]["line_start"], 21993)
        self.assertIn("old_call()", item["sources"][0]["content"])
        self.assertIn("new_call()", item["sources"][1]["content"])
        self.assertIn({"side": "both", "reason": "changed_source_excerpted"}, item["omissions"])
        request = model_contract.prepare_request(pack)
        self.assertEqual(len(request["sources"]), 2)
        self.assertIn("changed_source_excerpted", [value["reason"] for value in request["omissions"]])
        self.assertLessEqual(len(intake.encoded(pack)), intake.MAX_BYTES)

    def test_mismatched_or_truncated_patch_and_bad_blob_fail_closed(self):
        for api in (LargeModifiedFile(patch="@@ -22001 +22001 @@\n-wrong()\n+new_call()"),
                    LargeModifiedFile(patch="@@ -22001 +22001 @@\n-old_call()"),
                    LargeModifiedFile(corrupt=True)):
            with self.subTest(patch=api.patch, corrupt=api.corrupt):
                pack = intake.collect(REPO, 761, api)
                item = next(item for item in pack["files"] if item["after_path"] == "app.py")
                self.assertFalse(item["sources"])
                self.assertTrue(any(x["reason"] == "input_byte_limit" for x in item["omissions"]))

    def test_pair_exceeds_budget_even_if_each_side_fits(self):
        api = LargeModifiedFile(prefix_count=11000)
        self.assertLess(len(api.old), intake.MAX_BYTES)
        self.assertGreater(len(api.old) + len(api.new), intake.MAX_BYTES)
        pack = intake.collect(REPO, 761, api)
        item = next(item for item in pack["files"] if item["after_path"] == "app.py")
        self.assertEqual([source["side"] for source in item["sources"]], ["before", "after"])
        self.assertEqual(item["omissions"], [{"side": "both", "reason": "changed_source_excerpted"}])

    def test_untrusted_patch_with_impossible_coordinates_is_rejected(self):
        before = {"content": "a\n", "revision": BASE, "path": "app.py"}
        after = {"content": "b\n", "revision": HEAD, "path": "app.py"}
        self.assertEqual(changed_source.windows("@@ -400 +1 @@\n-a\n+b", before, after), [])
