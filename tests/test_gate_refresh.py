import sqlite3
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from hyperreview import gate_refresh, launchd, worker


REPO = "SoundBlaster/BuildHunter"
TARGET = {"workflow": "stack-gate.yml", "ref": "main"}


class GateRefreshTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.row_factory = sqlite3.Row
        self.db.execute("CREATE TABLE automatic_review_gates(job TEXT PRIMARY KEY, status TEXT)")
        self.db.execute("INSERT INTO automatic_review_gates VALUES ('job', 'completing')")
        self.config = {"review_gate": {"repositories": [REPO]}, "gate_refresh": {REPO: TARGET}}
        self.record = {"job": "job", "repository": REPO}

    def enqueue(self):
        gate_refresh.enqueue(self.db, self.config, self.record)

    def test_explicit_grant_and_safe_targets_required(self):
        for value in ({"other/repo": TARGET}, {REPO: {"workflow": "../unsafe.yml", "ref": "main"}},
                      {REPO: {"workflow": "stack-gate.yml", "ref": "main;bad"}}):
            with self.subTest(value=value), self.assertRaises(worker.WorkerError):
                gate_refresh.validate_options(value, [REPO])

    def test_launchd_plan_exposes_dispatch_authority(self):
        notice = launchd._installation_instructions(private_preview=True, review_gates=True, gate_refresh=True)
        self.assertIn(b"authorizes dispatching specified repository workflows", notice)

    def test_no_grant_means_no_queue(self):
        gate_refresh.enqueue(self.db, {"review_gate": {"repositories": [REPO]}}, self.record)
        self.assertIsNone(self.db.execute("SELECT name FROM sqlite_master WHERE name='automatic_gate_refreshes'").fetchone())

    @patch("hyperreview.gate_refresh.subprocess.run")
    def test_only_closed_gate_dispatches_once(self, run):
        run.return_value = SimpleNamespace(returncode=0)
        self.enqueue()
        self.enqueue()
        gate_refresh.drain(self.db, self.config["gate_refresh"], 1000)
        run.assert_not_called()
        self.db.execute("UPDATE automatic_review_gates SET status='completed'")
        gate_refresh.drain(self.db, self.config["gate_refresh"], 1000)
        gate_refresh.drain(self.db, self.config["gate_refresh"], 2000)
        run.assert_called_once()
        command = run.call_args.args[0]
        self.assertIn(f"repos/{REPO}/actions/workflows/stack-gate.yml/dispatches", command)
        self.assertEqual(run.call_args.kwargs["input"], b'{"ref": "main"}')

    @patch("hyperreview.gate_refresh.subprocess.run")
    def test_ambiguous_dispatch_is_bounded_and_delayed(self, run):
        run.side_effect = subprocess.TimeoutExpired("gh", 45)
        self.enqueue()
        self.db.execute("UPDATE automatic_review_gates SET status='completed'")
        for now in (1000, 1059, 1060, 1239, 1240, 2000):
            gate_refresh.drain(self.db, self.config["gate_refresh"], now)
        self.assertEqual(run.call_count, 3)

    @patch("hyperreview.gate_refresh.subprocess.run")
    def test_revoked_or_changed_grant_never_dispatches(self, run):
        self.enqueue()
        self.db.execute("UPDATE automatic_review_gates SET status='completed'")
        gate_refresh.drain(self.db, {}, 1000)
        gate_refresh.drain(self.db, {REPO: {"workflow": "other.yml", "ref": "main"}}, 1000)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
