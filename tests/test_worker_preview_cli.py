import contextlib
import io
from pathlib import Path
import unittest
from unittest.mock import patch

from hyperreview.__main__ import main


class WorkerPreviewCLITests(unittest.TestCase):
    def invoke(self, args):
        with patch("sys.argv", ["hyperreview", *args]), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return main()

    def flags(self):
        return ["worker-config", "--repo", "SoundBlaster/SessionMonitor", "--private-preview",
                "--allow-cloud-source", "--codex-executable", "/trusted/codex",
                "--codex-sha256", "a"*64, "--compiler", "/trusted/hypercode",
                "--compiler-sha256", "b"*64]

    def test_explicit_worker_preview_options_and_separate_default_state(self):
        with patch("hyperreview.worker.create_config", return_value=Path("/private/configs")) as create:
            self.assertEqual(self.invoke(self.flags()), 0)
        self.assertEqual(create.call_args.kwargs["state_root"].name, "preview-worker")
        options = create.call_args.kwargs["preview"]
        self.assertTrue(options["allow_cloud_source"])
        self.assertEqual(options["timeout_seconds"], 180)
        self.assertEqual(options["codex_sha256"], "a"*64)
        with patch("hyperreview.worker.create_config", return_value=Path("/private/configs")) as create:
            self.assertEqual(self.invoke([*self.flags(), "--preview-timeout-seconds", "0"]), 0)
        self.assertEqual(create.call_args.kwargs["preview"]["timeout_seconds"], 0)

    def test_missing_ack_or_pins_stop_before_config_creation(self):
        variants = [["worker-config", "--repo", "SoundBlaster/SessionMonitor", "--private-preview"],
                    ["worker-config", "--repo", "SoundBlaster/SessionMonitor", "--allow-cloud-source"],
                    ["worker-config", "--repo", "SoundBlaster/SessionMonitor", "--compiler", "/trusted/compiler"]]
        for args in variants:
            with self.subTest(args=args), patch("hyperreview.worker.create_config") as create:
                with self.assertRaises(SystemExit):
                    self.invoke(args)
                create.assert_not_called()

    def test_preview_failure_has_nonzero_exit_without_claiming_no_inference(self):
        with patch("hyperreview.worker.tick", return_value={"status":"preview_failed", "provider_attempts":None}):
            self.assertEqual(self.invoke(["worker-tick", "--config", "/private/config.json"]), 1)
