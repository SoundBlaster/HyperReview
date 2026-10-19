import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from hyperreview import intake, tracking
from hyperreview.publication import (COMMENT_MARKER, PublicationError,
                                    plan_publication, publish_comment)
from test_feedback import make_bundle


BASE = "a" * 40
HEAD = "b" * 40
MERGE_BASE = BASE


def confirmed_receipt(bundle):
    event = tracking.build_event(bundle)
    return {
        "schema": "hyperreview.tracking-receipt.v1",
        "correlation_id": event["correlation_id"],
        "attempt": 1,
        "tracking_status": "confirmed",
        "experiment_id": "1",
        "run_id": "run_123",
        "trace_id": "trace_123",
        "event_digest": intake.digest(event),
    }


class FakeGitHub:
    def __init__(self, *, account=intake.AUTHOR, pr=None, merge_base=MERGE_BASE,
                 comments=None, pages=None, final_account=None, final_pr=None):
        self.account = account
        self.pr = pr or {
            "number": 42, "state": "open", "draft": False,
            "author": intake.AUTHOR, "base_repo": "0al-spec/SpecGraph",
            "head_repo": "0al-spec/SpecGraph", "base_sha": "c" * 40,
            "head_sha": HEAD,
        }
        self.merge_base = merge_base
        self.comments = [] if comments is None else comments
        self.pages = pages
        self.final_account = final_account
        self.final_pr = final_pr
        self.calls = []
        self.user_calls = 0
        self.pr_calls = 0

    def get(self, endpoint, query="."):
        self.calls.append((endpoint, query))
        if endpoint == "user":
            self.user_calls += 1
            if self.user_calls > 1 and self.final_account is not None:
                return {"login": self.final_account}
            return {"login": self.account}
        if endpoint == "repos/0al-spec/SpecGraph/pulls/42":
            self.pr_calls += 1
            if self.pr_calls > 1 and self.final_pr is not None:
                return self.final_pr
            return self.pr
        if endpoint.startswith("repos/0al-spec/SpecGraph/compare/"):
            return {"merge_base_sha": self.merge_base}
        if "/issues/42/comments?" in endpoint:
            page = int(endpoint.rsplit("page=", 1)[1])
            if self.pages is not None:
                value = self.pages.get(page)
                if isinstance(value, Exception):
                    raise value
                return value if value is not None else []
            return self.comments if page == 1 else []
        raise AssertionError(f"Unexpected GitHub read: {endpoint}")


class RecordingWriter:
    def __init__(self, api, *, fail_after_write=False):
        self.api = api
        self.calls = []
        self.fail_after_write = fail_after_write

    def write_comment(self, repo, number, body, comment_id=None):
        self.calls.append((repo, number, body, comment_id))
        if comment_id is None:
            comment_id = max([item["id"] for item in self.api.comments] or [0]) + 1
            self.api.comments.append({"id": comment_id, "user": intake.AUTHOR, "body": body})
        else:
            next(item for item in self.api.comments if item["id"] == comment_id)["body"] = body
        if self.fail_after_write:
            raise PublicationError("simulated lost response")
        return {"id": comment_id, "body": body}


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="hyperreview-publication-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.bundle = self.root / "preview-bundle"
        _request, _result, _compiler, _diff, self.preview = make_bundle(self.bundle)
        (self.bundle / "tracking-receipt.json").write_bytes(
            intake.encoded(confirmed_receipt(self.bundle)))
        self.output_root = self.root / "plans"
        self.expected_hash = hashlib.sha256(self.preview).hexdigest()
        self.expected_body = COMMENT_MARKER + "\n\n" + self.preview.decode("utf-8")

    def plan(self, api=None, **kwargs):
        return plan_publication(
            self.bundle, expected_preview_sha256=self.expected_hash,
            output_root=self.output_root, api=api or FakeGitHub(), **kwargs)

    def test_historical_evidence_is_rejected_before_github_reads(self):
        from test_model_contract import pack, source

        historical_evidence = pack([
            source("before", "old source\n", "src/before.py"),
            source("after", "new source\n", "src/after.py"),
        ], state="closed", intake_mode="historical_read_only", publication_allowed=False,
            merged_at="2026-10-01T12:00:00Z", merge_commit_sha="d" * 40)
        bundle = self.root / "historical-preview"
        _request, _result, _compiler, _diff, preview = make_bundle(bundle, historical_evidence)
        (bundle / "tracking-receipt.json").write_bytes(
            intake.encoded(confirmed_receipt(bundle)))
        api = FakeGitHub()
        with self.assertRaisesRegex(PublicationError, "Historical read-only"):
            plan_publication(bundle, expected_preview_sha256=hashlib.sha256(preview).hexdigest(),
                             output_root=self.output_root, api=api)
        self.assertEqual(api.calls, [])

    def publish(self, directory, api, writer, **kwargs):
        raw_plan = (directory / "plan.json").read_bytes()
        body = (directory / "comment.md").read_bytes()
        return publish_comment(
            directory, expected_plan_sha256=hashlib.sha256(raw_plan).hexdigest(),
            expected_comment_sha256=hashlib.sha256(body).hexdigest(),
            authorized_repository="0al-spec/SpecGraph", authorized_mode="comment",
            state_root=self.root / "publish-state", api=api, writer=writer, **kwargs)

    def test_create_update_and_unchanged_match_own_marked_comment_exactly(self):
        destination, plan = self.plan()
        self.assertEqual(plan["status"], "ready")
        self.assertEqual(plan["action"], "create")
        self.assertIsNone(plan["comment_id"])

        old = {"id": 17, "user": intake.AUTHOR,
               "body": COMMENT_MARKER + "\n\nolder preview"}
        _destination, updated = self.plan(FakeGitHub(comments=[old]))
        self.assertEqual((updated["action"], updated["comment_id"]), ("update", 17))

        exact = {"id": 18, "user": intake.AUTHOR, "body": self.expected_body}
        _destination, unchanged = self.plan(FakeGitHub(comments=[exact]))
        self.assertEqual((unchanged["action"], unchanged["comment_id"]), ("unchanged", 18))
        self.assertEqual((destination / "comment.md").read_bytes(), self.expected_body.encode())

    def test_plan_is_private_dry_run_and_bundle_is_unchanged(self):
        before = {p.name: (p.read_bytes(), p.stat().st_mode & 0o777)
                  for p in self.bundle.iterdir() if p.is_file()}
        api = FakeGitHub()
        destination, plan = self.plan(api)
        after = {p.name: (p.read_bytes(), p.stat().st_mode & 0o777)
                 for p in self.bundle.iterdir() if p.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(plan["mode"], "dry_run")
        self.assertTrue(plan["authorization_required"])
        self.assertFalse(plan["writes_performed"])
        self.assertEqual((destination / "plan.json").stat().st_mode & 0o777, 0o600)
        self.assertEqual(destination.stat().st_mode & 0o777, 0o700)
        self.assertTrue(all("comments" in endpoint or endpoint == "user"
                            or "/pulls/" in endpoint or "/compare/" in endpoint
                            for endpoint, _ in api.calls))

    def test_stale_base_head_and_merge_base_block_with_stable_codes(self):
        cases = [
            (FakeGitHub(pr={**FakeGitHub().pr, "base_sha": "d" * 40}), "base_revision_changed"),
            (FakeGitHub(pr={**FakeGitHub().pr, "head_sha": "e" * 40}), "head_revision_changed"),
            (FakeGitHub(merge_base="f" * 40), "merge_base_changed"),
        ]
        for api, blocker in cases:
            with self.subTest(blocker=blocker):
                _destination, plan = self.plan(api)
                self.assertEqual(plan["status"], "blocked")
                self.assertIn(blocker, plan["blockers"])
                self.assertIsNone(plan["action"])

    def test_closed_draft_foreign_account_author_and_repo_are_blocked(self):
        baseline = FakeGitHub().pr
        cases = [
            (FakeGitHub(pr={**baseline, "state": "closed"}), "pr_not_open"),
            (FakeGitHub(pr={**baseline, "draft": True}), "pr_is_draft"),
            (FakeGitHub(account="other"), "authenticated_account_mismatch"),
            (FakeGitHub(pr={**baseline, "author": "other"}), "pr_author_mismatch"),
            (FakeGitHub(pr={**baseline, "head_repo": "fork/SpecGraph"}), "cross_repository_pr"),
        ]
        for api, blocker in cases:
            with self.subTest(blocker=blocker):
                _destination, plan = self.plan(api)
                self.assertEqual(plan["status"], "blocked")
                self.assertIn(blocker, plan["blockers"])

    def test_missing_or_pending_tracking_blocks_and_tampered_receipt_raises(self):
        receipt_path = self.bundle / "tracking-receipt.json"
        receipt_path.unlink()
        _destination, plan = self.plan()
        self.assertIn("tracking_unconfirmed", plan["blockers"])

        receipt_path.write_bytes(intake.encoded({
            "schema": "hyperreview.tracking-receipt.v1",
            "correlation_id": tracking.build_event(self.bundle)["correlation_id"],
            "attempt": 1, "tracking_status": "pending", "experiment_id": None,
            "run_id": None, "trace_id": None, "event_digest": None,
            "failure_code": "delivery_unavailable",
        }))
        _destination, pending = self.plan()
        self.assertIn("tracking_unconfirmed", pending["blockers"])

        receipt_path.write_bytes(intake.encoded({**confirmed_receipt(self.bundle),
                                                "event_digest": "0" * 64}))
        with self.assertRaises(PublicationError):
            self.plan()

    def test_tracking_receipt_symlink_and_fifo_are_rejected_without_blocking(self):
        receipt_path = self.bundle / "tracking-receipt.json"
        outside = self.root / "receipt.json"
        outside.write_bytes(receipt_path.read_bytes())
        receipt_path.unlink()
        receipt_path.symlink_to(outside)
        with self.assertRaises(PublicationError):
            self.plan()
        receipt_path.unlink()
        if hasattr(os, "mkfifo"):
            os.mkfifo(receipt_path)
            with self.assertRaises(PublicationError):
                self.plan()

    def test_preview_hash_and_bound_body_tampering_raise_without_output(self):
        with self.assertRaises(PublicationError):
            plan_publication(self.bundle, expected_preview_sha256="A" * 64,
                             output_root=self.output_root, api=FakeGitHub())
        self.assertFalse(self.output_root.exists())
        preview = self.bundle / "preview-compact.md"
        preview.write_bytes(preview.read_bytes() + b"tampered")
        with self.assertRaises(PublicationError):
            self.plan()

    def test_foreign_marker_is_ignored_and_duplicate_own_markers_block(self):
        foreign = {"id": 4, "user": "someone-else", "body": self.expected_body}
        _destination, plan = self.plan(FakeGitHub(comments=[foreign]))
        self.assertEqual(plan["action"], "create")
        own = {"id": 5, "user": intake.AUTHOR, "body": self.expected_body}
        other = {"id": 6, "user": intake.AUTHOR, "body": self.expected_body + "\nchanged"}
        _destination, duplicate = self.plan(FakeGitHub(comments=[own, other]))
        self.assertIn("duplicate_own_marker_comments", duplicate["blockers"])
        self.assertIsNone(duplicate["action"])

    def test_comment_pagination_is_bounded_and_failure_blocks(self):
        page = [{"id": i, "user": "someone-else", "body": "ordinary"}
                for i in range(1, 101)]
        api = FakeGitHub(pages={1: page, **{i: page for i in range(2, 11)}})
        _destination, plan = self.plan(api)
        self.assertIn("comment_inventory_incomplete", plan["blockers"])
        comment_calls = [endpoint for endpoint, _ in api.calls if "comments" in endpoint]
        self.assertEqual(len(comment_calls), 10)

        failing = FakeGitHub(pages={1: intake.IntakeError("private sentinel")})
        _destination, failed = self.plan(failing)
        self.assertIn("comment_inventory_incomplete", failed["blockers"])

        malformed = FakeGitHub(pages={1: [{"id": 1, "user": None, "body": "ordinary"}]})
        _destination, invalid = self.plan(malformed)
        self.assertIn("comment_inventory_incomplete", invalid["blockers"])

    def test_oversized_comment_body_is_not_persisted(self):
        with patch("hyperreview.publication.MAX_COMMENT_BYTES", 10):
            with self.assertRaises(PublicationError):
                self.plan()
        self.assertFalse(self.output_root.exists())

    def test_final_account_and_revision_races_block(self):
        api = FakeGitHub(final_account="changed")
        _destination, account_plan = self.plan(api)
        self.assertIn("authenticated_account_changed", account_plan["blockers"])
        changed_pr = {**FakeGitHub().pr, "head_sha": "f" * 40}
        api = FakeGitHub(final_pr=changed_pr)
        _destination, revision_plan = self.plan(api)
        self.assertIn("head_revision_changed", revision_plan["blockers"])

    def test_invalid_output_paths_and_non_private_root_are_rejected(self):
        with self.assertRaises(PublicationError):
            plan_publication(self.bundle, expected_preview_sha256=self.expected_hash,
                             output_root=self.bundle / "nested", api=FakeGitHub())
        self.output_root.mkdir(mode=0o755)
        self.output_root.chmod(0o755)
        with self.assertRaises(PublicationError):
            self.plan()

    def test_publish_requires_reviewed_digests_exact_authorization_and_fresh_state(self):
        api = FakeGitHub()
        directory, plan = self.plan(api)
        writer = RecordingWriter(api)
        result = self.publish(directory, api, writer)
        self.assertEqual(result["status"], "published")
        self.assertEqual(len(writer.calls), 1)
        self.assertEqual(writer.calls[0][3], None)
        self.assertTrue(writer.calls[0][2].startswith(COMMENT_MARKER))
        self.assertEqual((directory / "plan.json").stat().st_mode & 0o777, 0o600)

        with self.assertRaises(PublicationError):
            publish_comment(directory, expected_plan_sha256="0" * 64,
                            expected_comment_sha256=hashlib.sha256((directory / "comment.md").read_bytes()).hexdigest(),
                            authorized_repository="0al-spec/SpecGraph", authorized_mode="comment",
                            state_root=self.root / "other-state", api=FakeGitHub(), writer=RecordingWriter(FakeGitHub()))
        self.assertEqual(plan["status"], "ready")

    def test_publish_recovers_lost_post_response_without_duplicate(self):
        api = FakeGitHub()
        directory, _plan = self.plan(api)
        writer = RecordingWriter(api, fail_after_write=True)
        result = self.publish(directory, api, writer)
        self.assertEqual(result["status"], "published")
        self.assertEqual(len(api.comments), 1)
        self.assertEqual(len(writer.calls), 1)

    def test_publish_recovers_marker_after_restart_from_pending_receipt(self):
        api = FakeGitHub()
        directory, _plan = self.plan(api)
        expected_body = (directory / "comment.md").read_text()
        api.comments.append({"id": 29, "user": intake.AUTHOR, "body": expected_body})
        raw_plan = (directory / "plan.json").read_bytes()
        body_bytes = (directory / "comment.md").read_bytes()
        state_root = self.root / "publish-state"
        state_root.mkdir(mode=0o700)
        key = hashlib.sha256(b"0al-spec/SpecGraph#42").hexdigest()
        (state_root / (key + ".json")).write_bytes(intake.encoded({
            "schema": "hyperreview.publication-receipt.v1",
            "repository": "0al-spec/SpecGraph", "pr": 42,
            "plan_sha256": hashlib.sha256(raw_plan).hexdigest(),
            "comment_sha256": hashlib.sha256(body_bytes).hexdigest(),
            "status": "pending", "comment_id": None,
        }))
        writer = RecordingWriter(api)
        result = publish_comment(
            directory, expected_plan_sha256=hashlib.sha256(raw_plan).hexdigest(),
            expected_comment_sha256=hashlib.sha256(body_bytes).hexdigest(),
            authorized_repository="0al-spec/SpecGraph", authorized_mode="comment",
            state_root=state_root, api=api, writer=writer)
        self.assertEqual(result, {"status": "published", "comment_id": 29})
        self.assertEqual(writer.calls, [])
        self.assertEqual(len(api.comments), 1)

    def test_publish_updates_only_the_reviewed_comment_id_and_repeat_is_idempotent(self):
        old = {"id": 77, "user": intake.AUTHOR,
               "body": COMMENT_MARKER + "\n\nprevious preview"}
        api = FakeGitHub(comments=[old])
        directory, _plan = self.plan(api)
        writer = RecordingWriter(api)
        first = self.publish(directory, api, writer)
        second = self.publish(directory, api, writer)
        self.assertEqual(first["status"], "published")
        self.assertEqual(second, {"status": "already_published", "comment_id": 77})
        self.assertEqual([call[3] for call in writer.calls], [77])
        self.assertEqual(len(api.comments), 1)

    def test_revision_race_marks_the_same_comment_stale(self):
        api = FakeGitHub()
        directory, _plan = self.plan(api)
        changed_pr = {**api.pr, "head_sha": "f" * 40}
        raced_api = FakeGitHub(final_pr=changed_pr)
        writer = RecordingWriter(raced_api)
        result = self.publish(directory, raced_api, writer)
        self.assertEqual(result["status"], "stale_after_write")
        self.assertEqual(result["comment_id"], 1)
        self.assertEqual(len(raced_api.comments), 1)
        self.assertIn("Stale preview", raced_api.comments[0]["body"])
        self.assertEqual([call[3] for call in writer.calls], [None, 1])

    def test_publish_rejects_stale_plan_before_any_write(self):
        api = FakeGitHub()
        directory, _plan = self.plan(api)
        stale_api = FakeGitHub(pr={**api.pr, "head_sha": "f" * 40})
        writer = RecordingWriter(stale_api)
        with self.assertRaises(PublicationError):
            self.publish(directory, stale_api, writer)
        self.assertEqual(writer.calls, [])


if __name__ == "__main__":
    unittest.main()
