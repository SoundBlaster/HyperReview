import base64
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hyperreview.intake import (AUTHOR, MAX_BYTES, IntakeError, collect, digest,
                               collect_historical, eligible, encoded, exclusion,
                               historical_eligible, preview, save, source)


REPO = "0al-spec/SpecGraph"
BASE = "a" * 40
HEAD = "b" * 40
PR = {"number": 761, "author": AUTHOR, "state": "open", "draft": False,
      "base_repo": REPO, "head_repo": REPO, "base_sha": BASE, "head_sha": HEAD}


def blob(raw):
    sha = hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()
    return sha, {"encoding": "base64", "content": base64.b64encode(raw).decode()}


class FakeGitHub:
    def __init__(self, stale=False, raw=b"print('hello')\n", mode="100644", historical=False,
                 historical_base_contains_head=False):
        self.calls = []
        self.reads = 0
        self.stale = stale
        self.raw = raw
        self.mode = mode
        self.historical = historical
        self.historical_base_contains_head = historical_base_contains_head
        self.sha, self.blob = blob(raw)

    def get(self, endpoint, query="."):
        self.calls.append(endpoint)
        if endpoint == "user":
            return {"login": AUTHOR}
        if endpoint.endswith("/pulls/761"):
            self.reads += 1
            return {**PR, "state": "closed" if self.historical else "open",
                    "merged_at": "2026-01-02T03:04:05Z" if self.historical else None,
                    "merge_commit_sha": "d" * 40 if self.historical else None,
                    "base_sha": HEAD if self.historical_base_contains_head else BASE,
                    "head_sha": "c" * 40 if self.stale and self.reads > 1 else HEAD}
        if endpoint.endswith("/commits/" + "d" * 40):
            return {"parents": ["e" * 40]}
        if "/compare/" in endpoint:
            merge_base = HEAD if self.historical_base_contains_head and "e" * 40 not in endpoint else BASE
            return {"merge_base_sha": merge_base, "files": [{"filename": "app.py", "status": "added"}]}
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

    def test_historical_pack_is_pinned_and_publication_disabled(self):
        pack = collect_historical(REPO, 761, FakeGitHub(historical=True))
        self.assertEqual(pack["intake_mode"], "historical_read_only")
        self.assertIs(pack["publication_allowed"], False)
        self.assertEqual(pack["merge_commit_sha"], "d" * 40)
        self.assertIn("historical read-only", preview(pack))

    def test_historical_intake_uses_merge_time_parent_when_current_base_contains_head(self):
        api = FakeGitHub(historical=True, historical_base_contains_head=True)
        pack = collect_historical(REPO, 761, api)
        self.assertEqual(pack["merge_base_sha"], BASE)
        self.assertEqual(pack["files"][0]["sources"][0]["side"], "after")
        self.assertIn("/commits/" + "d" * 40, api.calls[2])
        self.assertIn("/compare/" + "e" * 40 + "..." + HEAD, api.calls[3])

    def test_historical_intake_rejects_unmerged_or_forked_pr(self):
        with self.assertRaises(IntakeError):
            historical_eligible(REPO, 761, {**PR, "state": "closed",
                              "merged_at": None, "merge_commit_sha": "d" * 40}, AUTHOR)
        with self.assertRaises(IntakeError):
            historical_eligible(REPO, 761, {**PR, "state": "closed",
                              "head_repo": "contributor/fork",
                              "merged_at": "2026-01-02T03:04:05Z",
                              "merge_commit_sha": "d" * 40}, AUTHOR)

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

    def test_large_source_and_many_checks_keep_final_metadata_within_budget(self):
        class ManyChecks(FakeGitHub):
            def get(self, endpoint, query="."):
                if "/check-runs" in endpoint:
                    return {"total_count": 100, "check_runs": [
                        {"id": n, "name": f"ordinary-check-{n}", "status": "completed",
                         "conclusion": "success", "head_sha": HEAD} for n in range(100)]}
                return super().get(endpoint, query)
        with patch("hyperreview.intake.utc_now", return_value="2026-10-03T15:04:00.123456+00:00"):
            pack = collect(REPO, 761, ManyChecks(raw=b"x" * 245130))
        self.assertLessEqual(len(encoded(pack)), MAX_BYTES)
        self.assertEqual(len(pack["files"][0]["sources"]), 1)
        self.assertTrue(pack["checks"])
        self.assertLess(len(pack["checks"]), 100)
        self.assertIn("evidence_byte_limit", pack["check_omissions"])
        self.assertEqual(pack["scope"]["commit_status_contexts"], "not_collected")
        self.assertIn("rechecked_at", pack)
        claimed = pack.pop("evidence_digest")
        self.assertEqual(claimed, digest(pack))

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
