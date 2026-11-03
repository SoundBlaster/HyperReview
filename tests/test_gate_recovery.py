import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hyperreview import automatic_review_gate as gate, worker_preview
from test_worker import REPO


class GateReplyRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = {"repositories": [REPO], "review_gate": {
            "repositories": [REPO], "eta_seconds": 600, "state_root": str(self.root / "gates")}}
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.row_factory = sqlite3.Row
        gate._setup(self.db)
        worker_preview._setup(self.db)
        self.job = "a" * 64
        self.task = {"candidate": "b" * 64, "repository": REPO, "pr": 761,
                     "base_sha": "c" * 40, "head_sha": "d" * 40}
        values = (self.job, self.task["candidate"], REPO, 761, self.task["base_sha"], self.task["head_sha"],
                  json.dumps([REPO]), "SoundBlaster", "e" * 20, "source.py", 1, "later", "now",
                  "plan", "a" * 64, "b" * 64, "c" * 64, "thread-node", "https://example.test/gate",
                  "needs_attention", 1, gate._grant(self.config))
        self.db.execute("""INSERT INTO automatic_review_gates
           (job,candidate,repository,pr,base_sha,head_sha,grant_repositories,account,gate_id,path,line,
            expected_completion,started_at,plan_dir,plan_sha256,comment_sha256,body_sha256,thread_id,url,
            status,updated_at,grant_digest) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", values)
        self.db.execute("INSERT INTO preview_jobs(job,candidate,settings,state,updated_at) VALUES (?,?,?,?,?)",
                        (self.job, self.task["candidate"], "s", "preview_ready", 1))
        self.db.execute("UPDATE automatic_review_gates SET reply_attempts=1 WHERE job=?", (self.job,))
        self.db.execute("INSERT INTO automatic_gate_replies VALUES (?,?)", (self.job, "preview_ready"))
        self.db.commit()

    def uncertain_reply(self, *args):
        gate._set(self.db, self.job, status="needs_attention", failure_code="reply_unconfirmed")
        raise gate.GateError("review_gate_write_uncertain")

    def resolve(self, db, record, **kwargs):
        gate._set(db, self.job, status="completed", completion_outcome="preview_ready", failure_code=None)

    def test_unconfirmed_reply_resolves_without_reposting(self):
        with patch.object(gate, "_api", return_value=object()), \
             patch.object(gate, "_fresh"), \
             patch.object(gate, "_bound_thread", return_value=("thread-node", "SoundBlaster", False)), \
             patch.object(gate, "_reply_once", side_effect=self.uncertain_reply), \
             patch.object(gate, "_write_rest") as post, \
             patch.object(gate, "_resolve", side_effect=self.resolve) as resolve:
            self.assertEqual(gate.complete(self.db, self.root, self.config, self.task, self.job, "success"),
                             "https://example.test/gate")
            resolve.assert_called_once()
            post.assert_not_called()
        self.assertEqual(self.db.execute("select reason from automatic_gate_recoveries").fetchone()[0],
                         "unconfirmed_reply_after_preview")
        self.assertEqual(self.db.execute("select status from automatic_review_gates").fetchone()[0], "completed")

    def test_crash_after_remote_resolve_recovers_without_fabricating_reply(self):
        with patch.object(gate, "_api", return_value=object()), patch.object(gate, "_fresh"), \
             patch.object(gate, "_bound_thread", return_value=("thread-node", "SoundBlaster", False)), \
             patch.object(gate, "_reply_once", side_effect=self.uncertain_reply), \
             patch.object(gate, "_resolve", side_effect=gate.GateError("review_gate_unavailable")):
            with self.assertRaises(gate.GateError):
                gate.complete(self.db, self.root, self.config, self.task, self.job, "success")
        with patch.object(gate, "_api", return_value=object()), patch.object(gate, "_fresh"), \
             patch.object(gate, "_bound_thread", return_value=("thread-node", "SoundBlaster", True)), \
             patch.object(gate, "_reply_once") as reply, patch.object(gate, "_write_rest") as post:
            gate.complete(self.db, self.root, self.config, self.task, self.job, "success")
            reply.assert_not_called()
            post.assert_not_called()
        self.assertEqual(self.db.execute("select status from automatic_review_gates").fetchone()[0], "completed")

    def test_missing_preview_never_releases_gate(self):
        self.db.execute("update preview_jobs set state='failed'")
        with patch.object(gate, "_resolve") as resolve:
            with self.assertRaises(gate.GateError) as error:
                gate.complete(self.db, self.root, self.config, self.task, self.job, "success")
        self.assertEqual(error.exception.code, "review_gate_preview_not_committed")
        resolve.assert_not_called()

    def test_changed_revision_does_not_resolve(self):
        with patch.object(gate, "_api", return_value=object()), \
             patch.object(gate, "_bound_thread", return_value=("thread-node", "SoundBlaster", False)), \
             patch.object(gate, "_fresh", side_effect=gate.GateError("review_gate_binding_changed")), \
             patch.object(gate, "_resolve") as resolve:
            with self.assertRaises(gate.GateError):
                gate.complete(self.db, self.root, self.config, self.task, self.job, "success")
            resolve.assert_not_called()
        self.assertEqual(self.db.execute("select count(*) from automatic_gate_recoveries").fetchone()[0], 0)

    def test_missing_recorded_reply_attempt_does_not_resolve(self):
        self.db.execute("update automatic_review_gates set reply_attempts=0")
        with patch.object(gate, "_api", return_value=object()), patch.object(gate, "_fresh"), \
             patch.object(gate, "_bound_thread", return_value=("thread-node", "SoundBlaster", False)), \
             patch.object(gate, "_reply_once", side_effect=self.uncertain_reply), \
             patch.object(gate, "_resolve") as resolve:
            with self.assertRaises(gate.GateError):
                gate.complete(self.db, self.root, self.config, self.task, self.job, "success")
            resolve.assert_not_called()

    def test_reserved_reply_missing_in_inventory_is_not_reposted(self):
        with patch.object(gate, "_api", return_value=object()), patch.object(gate, "_fresh"), \
             patch.object(gate, "_bound_thread", return_value=("thread-node", "SoundBlaster", False)), \
             patch.object(gate, "_find_reply", return_value=None), \
             patch.object(gate, "_write_rest") as post, \
             patch.object(gate, "_resolve", side_effect=self.resolve):
            gate.complete(self.db, self.root, self.config, self.task, self.job, "success")
            post.assert_not_called()
        self.assertEqual(self.db.execute("select count(*) from automatic_gate_replies").fetchone()[0], 1)
        self.assertEqual(self.db.execute("select status from automatic_review_gates").fetchone()[0], "completed")
