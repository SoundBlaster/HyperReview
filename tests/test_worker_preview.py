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

    def test_run_prepares_and_generates_without_waiting_then_never_replays(self):
        with patch("hyperreview.worker_generation.run", return_value=self.completed()) as run:
            api = WorkerGitHub()
            with patch("hyperreview.worker.time.time", return_value=10000):
                result = worker.run(self.config, api=api)
            self.assertEqual(result["status"], "preview_ready")
            self.assertEqual(sum("/pulls?" in endpoint for endpoint in api.calls), 1)
            self.assertEqual(result["github_writes"], 0)
            early = WorkerGitHub()
            self.assertEqual(self.tick(10001, early)["status"], "not_due")
            self.assertEqual(early.calls, [])
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
        def generated(*args, **kwargs):
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
        def generated(*args, **kwargs):
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


class GateRetryTests(unittest.TestCase):
    tick = WorkerPreviewTests.tick
    completed = WorkerPreviewTests.completed

    def setUp(self):
        WorkerPreviewTests.setUp(self)
        self.config = worker.create_config(repositories=[REPO], state_root=self.state,
            output_root=self.root / "gated-configs", preview=self.options,
            review_gate={"repositories": [REPO], "eta_seconds": 600,
                         "state_root": str(self.root / "gate")}) / "config.json"

    def test_retry_delays_survive_new_ticks_and_generation_runs_once(self):
        from hyperreview.automatic_review_gate import GateError
        self.tick()
        with patch("hyperreview.automatic_review_gate.reconcile"), \
             patch("hyperreview.automatic_review_gate.ensure",
                   side_effect=[GateError("review_gate_unavailable"), GateError("review_gate_write_uncertain"), "https://example.test/gate"]) as ensure, \
             patch("hyperreview.worker_preview._finish_gate", return_value={}) as finish, \
             patch("hyperreview.worker_generation.run", return_value=self.completed()) as generate:
            self.assertEqual(self.tick(10300)["retry_after"], 10360)
            self.assertEqual(self.tick(10359)["status"], "not_due")
            self.assertEqual(ensure.call_count, 1)
            self.assertEqual(self.tick(10360)["retry_after"], 10540)
            self.assertEqual(self.tick(10539)["status"], "not_due")
            self.assertEqual(ensure.call_count, 2)
            self.assertEqual(self.tick(10540)["status"], "preview_ready")
            self.assertEqual(ensure.call_count, 3)
            self.assertEqual(generate.call_count, 1)
            self.assertEqual(finish.call_count, 1)

    def test_third_unavailable_releases_gate_and_stops(self):
        from hyperreview.automatic_review_gate import GateError
        self.tick()
        with patch("hyperreview.automatic_review_gate.reconcile"), \
             patch("hyperreview.automatic_review_gate.ensure", side_effect=GateError("review_gate_unavailable")) as ensure, \
             patch("hyperreview.worker_preview._finish_gate", return_value={}) as finish, \
             patch("hyperreview.worker_generation.run") as generate:
            self.tick(10300); self.tick(10360)
            result = self.tick(10540)
            self.assertEqual(result["status"], "preview_failed")
            self.assertEqual(result["failure_code"], "review_gate_unavailable")
            self.tick(10840)
            self.assertEqual(ensure.call_count, 3)
            generate.assert_not_called()
            self.assertEqual(finish.call_args.args[5], "failed")

    def test_binding_change_is_not_retried(self):
        from hyperreview.automatic_review_gate import GateError
        self.tick()
        with patch("hyperreview.automatic_review_gate.reconcile"), \
             patch("hyperreview.automatic_review_gate.ensure", side_effect=GateError("review_gate_binding_changed")) as ensure, \
             patch("hyperreview.worker_preview._finish_gate", return_value={}):
            self.assertEqual(self.tick(10300)["status"], "preview_failed")
            self.tick(10360)
            self.assertEqual(ensure.call_count, 1)

    def test_interrupted_gate_attempt_waits_and_uses_same_job(self):
        self.tick()
        with patch("hyperreview.automatic_review_gate.reconcile"), \
             patch("hyperreview.automatic_review_gate.ensure", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.tick(10300)
        with worker._state(self.state) as db:
            before = dict(db.execute("SELECT * FROM preview_jobs").fetchone())
            self.assertEqual((before["gate_attempts"], before["gate_retry_after"]), (1, 10360))
        with patch("hyperreview.automatic_review_gate.reconcile"), \
             patch("hyperreview.automatic_review_gate.ensure", return_value="https://example.test/gate") as ensure, \
             patch("hyperreview.worker_preview._finish_gate", return_value={}), \
             patch("hyperreview.worker_generation.run", return_value=self.completed()):
            self.tick(10359)
            ensure.assert_not_called()
            self.assertEqual(self.tick(10360)["status"], "preview_ready")
        with worker._state(self.state) as db:
            after = dict(db.execute("SELECT * FROM preview_jobs").fetchone())
            self.assertEqual(after["job"], before["job"])
            self.assertEqual(after["gate_attempts"], 2)

    def test_uncertain_creation_recovers_without_another_post(self):
        from unittest.mock import MagicMock
        from hyperreview import automatic_review_gate as gate
        task = {"candidate": "a" * 64, "repository": REPO, "pr": 761,
                "base_sha": "b" * 40, "head_sha": "c" * 40}
        config = worker.load_config(self.config)
        record = {**task, "job": "d" * 64, "status": "checking",
                  "grant_repositories": json.dumps([REPO], separators=(",", ":"))}
        db = MagicMock()
        db.execute.return_value.fetchone.return_value = record
        with patch.object(gate, "_setup"), patch.object(gate, "_authorized"), \
             patch.object(gate, "_api", return_value=object()), \
             patch.object(gate, "_recover_creation", return_value="https://example.test/gate") as recover, \
             patch("hyperreview.review_gate.publish_review_gate") as post:
            self.assertEqual(gate.ensure(db, self.state, config, task, record["job"]),
                             "https://example.test/gate")
            recover.assert_called_once()
            post.assert_not_called()

    def test_gate_api_unavailability_is_not_mislabeled_as_changed_binding(self):
        from hyperreview import automatic_review_gate as gate
        task = {"candidate": "a" * 64, "repository": REPO, "pr": 761,
                "base_sha": "b" * 40, "head_sha": "c" * 40}
        class Unavailable:
            def get(self, *args):
                raise OSError("synthetic network failure")
        with self.assertRaises(gate.GateError) as error:
            gate._fresh(Unavailable(), task)
        self.assertEqual(error.exception.code, "review_gate_unavailable")

    def test_gate_metadata_read_failure_is_retryable_but_ineligible_pr_is_not(self):
        from hyperreview import automatic_review_gate as gate
        task = {"candidate": "a" * 64, "repository": REPO, "pr": 761,
                "base_sha": "b" * 40, "head_sha": "c" * 40}
        class MetadataFailure:
            def get(self, endpoint, *args):
                if endpoint == "user":
                    return {"login": "SoundBlaster"}
                raise worker.intake.IntakeError("synthetic read failure")
        with self.assertRaises(gate.GateError) as error:
            gate._fresh(MetadataFailure(), task)
        self.assertEqual(error.exception.code, "review_gate_unavailable")
        with patch.object(gate.intake, "metadata", return_value={}), \
             patch.object(gate.intake, "eligible", side_effect=worker.intake.IntakeError("ineligible")):
            with self.assertRaises(gate.GateError) as error:
                gate._fresh(MetadataFailure(), task)
        self.assertEqual(error.exception.code, "review_gate_binding_changed")

    def test_reconcile_does_not_consume_queued_retry(self):
        from hyperreview import automatic_review_gate as gate
        from hyperreview.automatic_review_gate import GateError
        self.tick()
        with patch.object(gate, "reconcile"), patch.object(gate, "ensure", side_effect=GateError("review_gate_unavailable")):
            self.tick(10300)
        config = worker.load_config(self.config)
        with worker._state(self.state) as db:
            gate._setup(db)
            row = db.execute("SELECT j.job,t.* FROM preview_jobs j JOIN tasks t ON j.candidate=t.candidate").fetchone()
            values = (row["job"], row["candidate"], REPO, row["pr"], row["base_sha"], row["head_sha"],
                      json.dumps([REPO]), "SoundBlaster", "a" * 20, "source.py", 1, "later", "now",
                      "plan", "a" * 64, "b" * 64, "c" * 64, "checking", 10300, gate._grant(config))
            db.execute("""INSERT INTO automatic_review_gates
                (job,candidate,repository,pr,base_sha,head_sha,grant_repositories,account,gate_id,path,line,
                 expected_completion,started_at,plan_dir,plan_sha256,comment_sha256,body_sha256,status,updated_at,grant_digest)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", values)
            db.commit()
            with patch.object(gate, "_recover_creation") as recover:
                result = gate.reconcile(db, self.state, config, api_factory=WorkerGitHub)
                self.assertEqual(result, {"reconciled": 0, "pending": 0})
                recover.assert_not_called()

    def test_old_preview_journal_gets_retry_columns_without_losing_jobs(self):
        import sqlite3
        db = sqlite3.connect(":memory:")
        db.execute("""CREATE TABLE preview_jobs (job TEXT PRIMARY KEY, candidate TEXT NOT NULL, settings TEXT NOT NULL,
                   state TEXT NOT NULL, updated_at INTEGER NOT NULL, generation_runs INTEGER NOT NULL DEFAULT 0,
                   provider_attempts INTEGER, artifact TEXT, bundle_digest TEXT, failure_code TEXT)""")
        db.execute("INSERT INTO preview_jobs(job,candidate,settings,state,updated_at) VALUES ('a','b','c','queued',1)")
        worker_preview._setup(db)
        self.assertEqual(db.execute("SELECT gate_attempts,gate_retry_after FROM preview_jobs").fetchone(), (0, 0))

    def test_interrupted_third_attempt_is_not_replayed_a_fourth_time(self):
        from hyperreview.automatic_review_gate import GateError
        self.tick()
        with patch("hyperreview.automatic_review_gate.reconcile"), \
             patch("hyperreview.automatic_review_gate.ensure",
                   side_effect=[GateError("review_gate_unavailable"), GateError("review_gate_unavailable"), KeyboardInterrupt]) as ensure, \
             patch("hyperreview.worker_preview._finish_gate", return_value={}) as finish, \
             patch("hyperreview.worker_generation.run") as generate:
            self.tick(10300); self.tick(10360)
            with self.assertRaises(KeyboardInterrupt):
                self.tick(10540)
            result = self.tick(10541)
            self.assertEqual(result["failure_code"], "review_gate_attempts_exhausted")
            self.assertEqual(ensure.call_count, 3)
            generate.assert_not_called()
            self.assertEqual(finish.call_args.args[5], "failed")

    def test_gate_plan_github_read_failure_is_retryable(self):
        from hyperreview import automatic_review_gate as gate
        from unittest.mock import MagicMock
        config = worker.load_config(self.config)
        task = {"candidate": "a" * 64, "repository": REPO, "pr": 761,
                "base_sha": "b" * 40, "head_sha": "c" * 40}
        with patch.object(gate, "_fresh", return_value=("SoundBlaster", {})), \
             patch.object(gate, "_anchor", return_value=("source.py", 1)), \
             patch("hyperreview.review_gate.plan_review_gate", side_effect=worker.intake.IntakeError("network")):
            with self.assertRaises(gate.GateError) as error:
                gate._persist_plan(MagicMock(), task, "d" * 64, config, WorkerGitHub(), self.state)
        self.assertEqual(error.exception.code, "review_gate_unavailable")
