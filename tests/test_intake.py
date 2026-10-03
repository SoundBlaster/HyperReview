import base64
import hashlib
import tempfile
import unittest
from pathlib import Path

from hyperreview.intake import (AUTHOR, MAX_BYTES, IntakeError, collect, digest,
                               eligible, encoded, exclusion, save, source)


REPO = "0al-spec/SpecGraph"
BASE = "a" * 40
HEAD = "b" * 40
PR = {"number": 761, "author": AUTHOR, "state": "open", "draft": False,
      "base_repo": REPO, "head_repo": REPO, "base_sha": BASE, "head_sha": HEAD}


def blob(raw):
    sha = hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()
    return sha, {"encoding": "base64", "content": base64.b64encode(raw).decode()}


class FakeGitHub:
    def __init__(self, stale=False, raw=b"print('hello')\n", mode="100644"):
        self.calls = []
        self.reads = 0
        self.stale = stale
        self.raw = raw
        self.mode = mode
        self.sha, self.blob = blob(raw)

    def get(self, endpoint, query="."):
        self.calls.append(endpoint)
        if endpoint == "user":
            return {"login": AUTHOR}
        if endpoint.endswith("/pulls/761"):
            self.reads += 1
            return {**PR, "head_sha": "c" * 40 if self.stale and self.reads > 1 else HEAD}
        if "/compare/" in endpoint:
            return {"merge_base_sha": BASE, "files": [{"filename": "app.py", "status": "added"}]}
        if "/git/trees/" in endpoint:
            return {"truncated": False, "tree": [] if BASE in endpoint else [
                {"path": "app.py", "mode": self.mode, "type": "blob",
                 "sha": self.sha, "size": len(self.raw)}]}
        if "/git/blobs/" in endpoint:
            return self.blob
        if "/check-runs" in endpoint:
            return {"total_count": 2, "check_runs": [
                {"id": 1, "name": "compile", "status": "completed", "conclusion": "success", "head_sha": HEAD},
                {"id": 2, "name": "old", "status": "completed", "conclusion": "success", "head_sha": BASE}]}
        raise AssertionError(endpoint)


class IntakeTests(unittest.TestCase):
    def test_eligibility_rejects_foreign_author_fork_draft_closed_account(self):
        eligible(REPO, 761, PR, AUTHOR)
        for change in ({"author": "other"}, {"head_repo": "other/fork"},
                       {"draft": True}, {"state": "closed"}):
            with self.subTest(change=change), self.assertRaises(IntakeError):
                eligible(REPO, 761, {**PR, **change}, AUTHOR)
        with self.assertRaises(IntakeError):
            eligible(REPO, 761, PR, "other")

    def test_allowlist_rejected_before_any_api_access(self):
        api = FakeGitHub()
        with self.assertRaises(IntakeError):
            collect("other/repo", 1, api)
        self.assertEqual(api.calls, [])

    def test_path_filter(self):
        for path in ("../app.py", "/app.py", "a//app.py", "app\n.py", "AGENTS.md",
                     ".codex/settings.md", ".env", "credential.py", "private.key", "image.png"):
            with self.subTest(path=path):
                self.assertIsNotNone(exclusion(path))
        self.assertIsNone(exclusion("src/app.py"))

    def test_pack_digest_scope_revisions_and_check_provenance(self):
        pack = collect(REPO, 761, FakeGitHub())
        self.assertLessEqual(len(encoded(pack)), MAX_BYTES)
        self.assertEqual(pack["merge_base_sha"], BASE)
        record = pack["files"][0]["sources"][0]
        self.assertEqual((record["revision"], record["line_start"], record["line_end"]), (HEAD, 1, 1))
        self.assertEqual(record["trust"], "untrusted_source_data")
        self.assertEqual([c["id"] for c in pack["checks"]], [1])
        self.assertIn("revision_mismatch", pack["check_omissions"])
        claimed = pack.pop("evidence_digest")
        self.assertEqual(claimed, digest(pack))

    def test_symlink_and_oversized_file_never_fetched(self):
        for api, reason in ((FakeGitHub(mode="120000"), "symlink_or_nonregular"),
                            (FakeGitHub(raw=b"x" * MAX_BYTES), "input_byte_limit")):
            pack = collect(REPO, 761, api)
            self.assertEqual(pack["files"][0]["sources"], [])
            self.assertEqual(pack["files"][0]["omissions"][0]["reason"], reason)
            self.assertFalse(any("/git/blobs/" in call for call in api.calls))

    def test_stale_revision_rejected(self):
        with self.assertRaises(IntakeError):
            collect(REPO, 761, FakeGitHub(stale=True))

    def test_truncated_tree_fails_without_reading_blobs(self):
        class Truncated(FakeGitHub):
            def get(self, endpoint, query="."):
                if "/git/trees/" in endpoint:
                    return {"truncated": True, "tree": []}
                return super().get(endpoint, query)
        api = Truncated()
        with self.assertRaises(IntakeError):
            collect(REPO, 761, api)
        self.assertFalse(any("/git/blobs/" in call for call in api.calls))

    def test_file_limit_and_changed_directories(self):
        class ManyFiles(FakeGitHub):
            def get(self, endpoint, query="."):
                if "/git/trees/" in endpoint and HEAD in endpoint:
                    return {"truncated": False, "tree": [
                        {"path": "src", "mode": "040000", "type": "tree", "sha": HEAD},
                        *[{"path": f"src/{n:02}.py", "mode": "100644", "type": "blob",
                           "sha": self.sha, "size": len(self.raw)} for n in range(31)]]}
                return super().get(endpoint, query)
        api = ManyFiles()
        pack = collect(REPO, 761, api)
        self.assertEqual(len(pack["files"]), 31)
        self.assertEqual(sum(bool(f["sources"]) for f in pack["files"]), 30)
        self.assertEqual(pack["files"][-1]["omissions"][0]["reason"], "source_file_limit")

    def test_encoded_unicode_bytes_stay_bounded(self):
        pack = collect(REPO, 761, FakeGitHub(raw=("я" * 45000).encode()))
        self.assertLessEqual(len(encoded(pack)), MAX_BYTES)
        self.assertEqual(pack["files"][0]["sources"], [])
        self.assertEqual(pack["files"][0]["omissions"][0]["reason"], "encoded_evidence_byte_limit")

    def test_binary_and_blob_integrity(self):
        api = FakeGitHub(raw=b"a\0b")
        entries = {"app.py": {"type": "blob", "mode": "100644", "sha": api.sha, "size": 3}}
        self.assertEqual(source(api, REPO, HEAD, "app.py", entries, 100)[1], "binary_content")
        api.blob = blob(b"different")[1]
        self.assertEqual(source(api, REPO, HEAD, "app.py", entries, 100)[1], "blob_integrity_failure")

    def test_private_output_and_symlink_rejection(self):
        pack = collect(REPO, 761, FakeGitHub())
        with tempfile.TemporaryDirectory() as folder:
            # macOS /var may itself be a symlink: use canonical operator root.
            root = Path(folder).resolve()
            destination = save(pack, root / "output")
            self.assertEqual(destination.stat().st_mode & 0o777, 0o700)
            self.assertEqual((destination / "evidence.json").stat().st_mode & 0o777, 0o600)
            (root / "link").symlink_to(root / "output", target_is_directory=True)
            with self.assertRaises(IntakeError):
                save(pack, root / "link")


if __name__ == "__main__":
    unittest.main()
