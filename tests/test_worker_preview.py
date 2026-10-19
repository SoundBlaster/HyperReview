import hashlib
import json
import os
from pathlib import Path
import plistlib
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from hyperreview import worker, worker_preview
from hyperreview.launchd import write_launchd_plan
from hyperreview.worker_generation import PreviewJobError
from test_worker import WorkerGitHub, REPO


class WorkerPreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.state = self.root / "state"
        self.options = {
            "allow_cloud_source": True, "codex_executable": str(self.root / "codex"),
            "codex_sha256": "a" * 64, "compiler": str(self.root / "compiler"),
            "compiler_sha256": "b" * 64, "model": "gpt-6-luna",
            "reasoning_effort": "low", "timeout_seconds": 180,
        }
        self.config = worker.create_config(repositories=[REPO], state_root=self.state,
            output_root=self.root / "configs", preview=self.options) / "config.json"
        self.artifacts = {name: b"{}" for name in worker_preview.FILES}
        self.artifacts["preview-compact.md"] = b"# Synthetic private preview\n"

    def tick(self, timestamp=10000, api=None):
        with patch("hyperreview.worker.time.time", return_value=timestamp):
            return worker.tick(self.config, api=api or WorkerGitHub())

    def completed(self):
        return {"artifacts": dict(self.artifacts), "provider_attempts": 1}

    def test_one_intake_then_one_private_preview_then_no_replay(self):
        with patch("hyperreview.worker_generation.run", return_value=self.completed()) as run:
            self.assertEqual(self.tick()["status"], "request_prepared")
            run.assert_not_called()
            self.assertEqual(self.tick(10001)["status"], "not_due")
            result = self.tick(10300)
            self.assertEqual(result["status"], "preview_ready")
            self.assertEqual(result["github_writes"], 0)
            self.assertEqual(self.tick(10600)["status"], "idle")
            self.assertEqual(run.call_count, 1)
        bundle = Path(result["bundle"])
        self.assertEqual({p.name for p in bundle.iterdir()}, worker_preview.FILES)
        self.assertEqual((bundle / "preview-compact.md").stat().st_mode & 0o777, 0o600)
        status = worker.status(self.config)
        self.assertEqual(status["delivery_mode"], "private_preview")
        self.assertEqual(len(status["previews"]), 1)
        self.assertEqual(status["previews"][0]["tracking_status"], "not_started")
        self.assertNotIn("Synthetic", json.dumps(status))

    def test_revisions_changed_before_generation_make_job_stale(self):
        self.tick()
        with patch("hyperreview.worker_generation.run") as run:
            result = self.tick(10300, WorkerGitHub(revision_changed=True))
        self.assertEqual(result["status"], "preview_stale")
        self.assertEqual(result["generation_runs"], 0)
        run.assert_not_called()

    def test_change_during_generation_discards_preview_and_does_not_replay(self):
        self.tick()
        api = WorkerGitHub()
        def generated(*args):
            api.revision_changed = True
            return self.completed()
        with patch("hyperreview.worker_generation.run", side_effect=generated) as run:
            result = self.tick(10300, api)
            self.assertEqual(result["status"], "preview_stale")
            self.assertEqual(self.tick(10600)["status"], "idle")
            self.assertEqual(run.call_count, 1)
        self.assertFalse((self.state / "previews").exists())

    def test_final_observation_uses_new_deadline_after_discovery_client_expires(self):
        self.tick()
        clock = [10.0]
        class DeadlineGitHub(WorkerGitHub):
            def __init__(self):
                super().__init__()
                self.deadline = clock[0] + 300
            def get(self, endpoint, query="."):
                if clock[0] >= self.deadline:
                    raise worker.intake.IntakeError("expired synthetic client")
                return super().get(endpoint, query)
        clients = []
        def factory():
            client = DeadlineGitHub()
            clients.append(client)
            return client
        def generated(*args):
            clock[0] += 301
            return self.completed()
        with patch("hyperreview.worker.intake.GitHub", side_effect=factory), \
                patch("hyperreview.worker.time.monotonic", side_effect=lambda: clock[0]), \
                patch("hyperreview.worker.time.time", return_value=10300), \
                patch("hyperreview.worker_generation.run", side_effect=generated):
            result = worker.tick(self.config)
        self.assertEqual(result["status"], "preview_ready")
        self.assertEqual(len(clients), 3)  # Discovery, pre-inference and final observation.
        self.assertLess(clients[0].deadline, clock[0])
        self.assertEqual(clients[-1].deadline, clock[0] + 30)

    def test_failed_job_never_automatically_repeats_cloud_request(self):
        self.tick()
        with patch("hyperreview.worker_generation.run", side_effect=PreviewJobError("generation_failed")) as run:
            result = self.tick(10300)
            self.assertEqual(result["status"], "preview_failed")
            self.assertEqual(result["failure_code"], "generation_failed")
            self.assertIsNone(result["provider_attempts"])
            self.assertEqual(self.tick(10600)["status"], "idle")
            self.assertEqual(run.call_count, 1)

    def test_interrupted_queued_job_resumes_before_any_generation(self):
        self.tick()
        with patch("hyperreview.worker_preview._fresh", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.tick(10300)
        with worker._state(self.state) as db:
            row = db.execute("SELECT state,generation_runs FROM preview_jobs").fetchone()
            self.assertEqual(tuple(row), ("queued", 0))
        with patch("hyperreview.worker_generation.run", return_value=self.completed()) as run:
            self.assertEqual(self.tick(10600)["status"], "preview_ready")
            self.assertEqual(self.tick(10900)["status"], "idle")
            self.assertEqual(run.call_count, 1)
        with worker._state(self.state) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM preview_jobs").fetchone()[0], 1)

    def test_interrupted_job_is_recorded_and_never_replayed(self):
        self.tick()
        with patch("hyperreview.worker_generation.run", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.tick(10300)
        with worker._state(self.state) as db:
            self.assertEqual(db.execute("SELECT state FROM preview_jobs").fetchone()[0], "analyzing")
        with patch("hyperreview.worker_generation.run") as run:
            self.assertEqual(self.tick(10600)["status"], "idle")
            run.assert_not_called()
        with worker._state(self.state) as db:
            row = db.execute("SELECT state,failure_code,generation_runs FROM preview_jobs").fetchone()
            self.assertEqual(tuple(row), ("failed", "interrupted_no_replay", 1))

    def test_retention_removes_private_bundle_but_preserves_receipt_without_replay(self):
        self.tick()
        with patch("hyperreview.worker_generation.run", return_value=self.completed()) as run:
            result = self.tick(10300)
            bundle = Path(result["bundle"])
            os.utime(bundle, (1, 1))
            self.tick(worker.RETENTION_SECONDS + 10600)
            self.assertEqual(run.call_count, 1)
        self.assertFalse(bundle.exists())
        self.assertEqual(worker.status(self.config)["previews"], [])
        with worker._state(self.state) as db:
            row = db.execute("SELECT state,artifact,bundle_digest FROM preview_jobs").fetchone()
            self.assertEqual(row["state"], "preview_ready")
            self.assertIsNone(row["artifact"])
            self.assertIsNotNone(row["bundle_digest"])

    def test_tampered_bundle_is_not_reported_as_ready(self):
        self.tick()
        with patch("hyperreview.worker_generation.run", return_value=self.completed()):
            result = self.tick(10300)
        (Path(result["bundle"]) / "preview-compact.md").write_text("changed")
        with self.assertRaises(worker.WorkerError):
            worker.status(self.config)

    def test_config_change_creates_new_job_and_filters_old_preview(self):
        self.tick()
        with patch("hyperreview.worker_generation.run", return_value=self.completed()) as run:
            self.tick(10300)
            config = json.loads(self.config.read_text())
            config["preview"]["reasoning_effort"] = "medium"
            self.config.write_text(json.dumps(config))
            self.assertEqual(worker.status(self.config)["previews"], [])
            self.assertEqual(self.tick(10600)["status"], "preview_ready")
            self.assertEqual(run.call_count, 2)
        self.assertEqual(worker.status(self.config)["preview_counts"], {"stale": 1, "preview_ready": 1})

    def test_removing_preview_options_restores_intake_only_mode(self):
        self.tick()
        config = json.loads(self.config.read_text())
        config.pop("preview")
        config["schema"] = worker.CONFIG_SCHEMA
        self.config.write_text(json.dumps(config))
        with patch("hyperreview.worker_generation.run") as run:
            self.tick(10300)
            run.assert_not_called()
        self.assertEqual(worker.status(self.config)["delivery_mode"], "request_only")

    def test_legacy_config_cannot_hide_preview_settings(self):
        config = json.loads(self.config.read_text())
        config["schema"] = worker.CONFIG_SCHEMA
        self.config.write_text(json.dumps(config))
        with self.assertRaises(worker.WorkerError):
            worker.load_config(self.config)

    def test_preview_job_capacity_prevents_inference(self):
        self.tick()
        with worker._state(self.state) as db:
            worker_preview._setup(db)
            with db:
                db.execute("INSERT INTO preview_jobs (job,candidate,settings,state,updated_at) VALUES (?,?,?,?,?)",
                    ("full", "absent", "old", "failed", 1))
        with patch("hyperreview.worker.MAX_RECEIPTS", 1), patch("hyperreview.worker_generation.run") as run:
            result = self.tick(10300)
        self.assertEqual(result["status"], "preview_capacity_reached")
        run.assert_not_called()

    def test_preview_launchd_plan_has_its_own_label_and_truthful_instructions(self):
        plan = write_launchd_plan(config_path=self.config, python=Path(sys.executable), output_root=self.root/"plans")
        plist = plistlib.loads((plan/"agent.plist").read_bytes())
        self.assertEqual(plist["Label"], "com.hyperreview.preview")
        instructions = (plan/"installation.md").read_text()
        self.assertIn("isolated", instructions)
        self.assertNotIn("runs only the bounded worker", instructions)
        self.assertEqual(plist["ProgramArguments"][-1], str(self.config))
