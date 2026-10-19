import fcntl
import json
import os
from pathlib import Path
import plistlib
import sys
import tempfile
import unittest
from unittest.mock import patch

from hyperreview import intake, worker
from hyperreview.launchd import write_launchd_plan
from hyperreview.worker_task_eligibility import WorkerTaskContext, WorkerTaskEligibility
from test_intake import FakeGitHub, PR, REPO


class WorkerGitHub(FakeGitHub):
    def __init__(self, *, revision_changed=False, **kwargs):
        super().__init__(**kwargs)
        self.revision_changed = revision_changed

    def get(self, endpoint, query="."):
        if "/pulls?" in endpoint:
            self.calls.append(endpoint)
            return [dict(PR)]
        value = super().get(endpoint, query)
        if self.revision_changed and endpoint.endswith("/pulls/761"):
            return {**value, "head_sha": "c" * 40}
        return value


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.state = self.root / "state"
        self.config = worker.create_config(repositories=[REPO], state_root=self.state,
                                           output_root=self.root / "configs") / "config.json"

    def tick(self, timestamp=10000, api=None):
        with patch("hyperreview.worker.time.time", return_value=timestamp):
            return worker.tick(self.config, api=api or WorkerGitHub())

    def test_tick_prepares_pinned_request_and_deduplicates_next_cycle(self):
        result = self.tick()
        self.assertEqual(result["status"], "request_prepared")
        bundle = Path(result["bundle"])
        request = json.loads((bundle / "request.json").read_text())
        metadata = json.loads((bundle / "metadata.json").read_text())
        self.assertEqual(request["head_sha"], PR["head_sha"])
        self.assertEqual(metadata["request_digest"], request["request_digest"])
        self.assertEqual(metadata["model_calls"], 0)
        self.assertEqual(metadata["github_writes"], 0)
        self.assertEqual((bundle / "request.json").stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.tick(10300)["status"], "idle")
        self.assertEqual(len(worker.status(self.config)["handoffs"]), 1)

    def repositories(self, values):
        config = json.loads(self.config.read_text())
        self.config.write_text(json.dumps({**config, "repositories": values}))

    def test_reenabled_repository_restores_retained_handoff_without_collection(self):
        first = self.tick()
        self.repositories(["SoundBlaster/SessionMonitor"])
        self.tick(10300)
        self.assertEqual(worker.status(self.config)["handoffs"], [])
        self.repositories([REPO])
        with patch("hyperreview.worker.intake.collect") as collect:
            self.tick(10600)
            collect.assert_not_called()
        restored = worker.status(self.config)["handoffs"]
        self.assertEqual(restored[0]["bundle"], first["bundle"])
        with worker._state(self.state) as db:
            self.assertEqual(db.execute("SELECT attempts FROM tasks").fetchone()[0], 1)

    def test_pipeline_rollback_restores_original_candidate(self):
        with patch("hyperreview.worker._pipeline", return_value="a" * 64):
            first = self.tick()
        with patch("hyperreview.worker._pipeline", return_value="b" * 64):
            self.tick(10300)
        with patch("hyperreview.worker._pipeline", return_value="a" * 64), \
                patch("hyperreview.worker.intake.collect") as collect:
            self.tick(10600)
            collect.assert_not_called()
        self.assertEqual(worker.status(self.config)["handoffs"][0]["bundle"], first["bundle"])

    def test_reenabled_candidate_without_artifacts_retries_with_remaining_budget(self):
        self.tick()
        self.repositories(["SoundBlaster/SessionMonitor"])
        self.tick(10300)
        with worker._state(self.state) as db:
            db.execute("UPDATE tasks SET artifact=NULL")
            db.commit()
        self.repositories([REPO])
        self.assertEqual(self.tick(10600)["status"], "request_prepared")
        with worker._state(self.state) as db:
            self.assertEqual(db.execute("SELECT attempts FROM tasks").fetchone()[0], 2)

    def test_reenabling_does_not_reset_exhausted_attempt_budget(self):
        self.tick()
        self.repositories(["SoundBlaster/SessionMonitor"])
        self.tick(10300)
        with worker._state(self.state) as db:
            db.execute("UPDATE tasks SET artifact=NULL,attempts=2")
            db.commit()
        self.repositories([REPO])
        with patch("hyperreview.worker.intake.collect") as collect:
            self.assertEqual(self.tick(10600)["status"], "idle")
            collect.assert_not_called()
        with worker._state(self.state) as db:
            self.assertEqual(tuple(db.execute("SELECT state,attempts,failure_code FROM tasks").fetchone()),
                             ("failed", 2, "attempts_exhausted"))

    def test_interval_and_live_process_lock_prevent_duplicate_work(self):
        self.tick()
        api = WorkerGitHub()
        self.assertEqual(self.tick(10001, api)["status"], "not_due")
        self.assertEqual(api.calls, [])
        with (self.state / "worker.lock").open("rb") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(self.tick(10300, api)["status"], "busy")
        self.assertEqual(api.calls, [])

    def test_collection_retries_stop_after_two_attempts(self):
        with patch("hyperreview.worker.intake.collect", side_effect=intake.IntakeError("private")) as collect:
            self.assertEqual(self.tick()["status"], "failed")
            self.assertEqual(self.tick(10300)["status"], "failed")
            self.assertEqual(self.tick(10600)["status"], "idle")
            self.assertEqual(collect.call_count, 2)
        with worker._state(self.state) as db:
            row = db.execute("SELECT attempts,failure_code FROM tasks").fetchone()
            self.assertEqual(tuple(row), (2, "collection_or_request_failed"))
            self.assertNotIn("private", str(db.execute("SELECT * FROM events").fetchall()))

    def test_changed_revisions_do_not_create_a_handoff(self):
        result = self.tick(api=WorkerGitHub(revision_changed=True))
        self.assertEqual(result["status"], "stale")
        self.assertEqual(worker.status(self.config)["handoffs"], [])

    def test_interrupted_collection_recovers_without_resetting_attempts(self):
        with patch("hyperreview.worker.intake.collect", side_effect=OSError("interruption")):
            with self.assertRaises(OSError):
                self.tick()
        with worker._state(self.state) as db:
            self.assertEqual(tuple(db.execute("SELECT state,attempts FROM tasks").fetchone()),
                             ("collecting", 1))
        self.assertEqual(self.tick(10300)["status"], "request_prepared")
        with worker._state(self.state) as db:
            self.assertEqual(db.execute("SELECT attempts FROM tasks").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT count(*) FROM events WHERE failure_code='interrupted'")
                             .fetchone()[0], 1)

    def test_expiry_recovers_deleted_bundle_reference_and_keeps_receipt(self):
        result = self.tick()
        bundle = Path(result["bundle"])
        for path in bundle.iterdir():
            path.unlink()
        bundle.rmdir()
        self.assertEqual(worker.status(self.config)["handoffs"], [])
        with worker._state(self.state) as db:
            worker._expire_artifacts(db, self.state, 11000)
            row = db.execute("SELECT artifact,request_digest,state FROM tasks").fetchone()
            self.assertIsNone(row["artifact"])
            self.assertIsNotNone(row["request_digest"])
            self.assertEqual(row["state"], "request_prepared")

    def test_retention_removes_only_expired_owned_bundles(self):
        result = self.tick()
        bundle = Path(result["bundle"])
        os.utime(bundle, (1, 1))
        with worker._state(self.state) as db:
            worker._expire_artifacts(db, self.state, worker.RETENTION_SECONDS + 2)
            self.assertEqual(db.execute("SELECT count(*) FROM tasks").fetchone()[0], 1)
        self.assertFalse(bundle.exists())

    def test_queue_capacity_retains_page_cursor(self):
        api = WorkerGitHub()
        original = api.get

        def get(endpoint, query="."):
            if "/pulls?" in endpoint:
                return [dict(PR), {**PR, "number": 762}]
            return original(endpoint, query)

        api.get = get
        with patch("hyperreview.worker.MAX_PENDING", 1):
            result = self.tick(api=api)
        self.assertTrue(result["queue_full"])
        with worker._state(self.state) as db:
            self.assertEqual(worker._meta(db, "page:" + REPO, 1), 1)

    def test_config_rejects_added_authority_and_symlinks(self):
        config = json.loads(self.config.read_text())
        self.config.write_text(json.dumps({**config, "publish": True}))
        with self.assertRaises(worker.WorkerError):
            worker.load_config(self.config)
        self.config.write_text(json.dumps(config))
        link = self.config.with_name("link.json")
        link.symlink_to(self.config)
        with self.assertRaises(worker.WorkerError):
            worker.load_config(link)
        self.config.chmod(0o644)
        with self.assertRaises(worker.WorkerError):
            worker.load_config(self.config)

    def test_pure_retry_policy_has_explicit_terminal_and_not_due_cases(self):
        policy = WorkerTaskEligibility()
        for state, attempts, due, expected in (
            ("queued", 0, 0, True), ("failed", 1, 100, True),
            ("failed", 2, 0, False), ("request_prepared", 1, 0, False),
            ("stale", 0, 0, False), ("failed", 1, 101, False),
        ):
            with self.subTest(state=state, attempts=attempts, due=due):
                self.assertEqual(policy.is_satisfied_by(WorkerTaskContext(state, attempts, due, 100)),
                                 expected)

    def test_launchd_plan_has_only_read_only_tick_argv_and_is_not_installed(self):
        plan = write_launchd_plan(config_path=self.config, python=Path(sys.executable),
                                 output_root=self.root / "plans")
        data = plistlib.loads((plan / "agent.plist").read_bytes())
        self.assertEqual(data["ProgramArguments"], [sys.executable, "-B", "-m", "hyperreview",
                                                    "worker-tick", "--config", str(self.config)])
        self.assertEqual(data["StartInterval"], 300)
        self.assertFalse(data["RunAtLoad"])
        self.assertNotIn("KeepAlive", data)
        self.assertNotIn("GH_TOKEN", data["EnvironmentVariables"])
        self.assertEqual((plan / "agent.plist").stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
