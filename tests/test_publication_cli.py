import contextlib
import io
from pathlib import Path
import unittest
from unittest.mock import patch

from hyperreview.__main__ import main


class PublicationCliTests(unittest.TestCase):
    def test_ready_and_blocked_exit_codes_do_not_print_comment(self):
        for status, code, blockers in (("ready", 0, []), ("blocked", 2, ["stale_head"])):
            output = io.StringIO()
            args = ["hyperreview", "publish-plan", "--bundle", "/private/preview",
                    "--expected-preview-sha256", "a" * 64]
            plan = {"status": status, "blockers": blockers, "body": "private comment body"}
            with self.subTest(status=status), patch("sys.argv", args), contextlib.redirect_stdout(output), patch(
                    "hyperreview.publication.plan_publication", return_value=(Path("/private/plans/id"), plan)) as call:
                self.assertEqual(main(), code)
            self.assertEqual(call.call_args.args, (Path("/private/preview"),))
            self.assertEqual(call.call_args.kwargs["expected_preview_sha256"], "a" * 64)
            self.assertIn("GitHub writes: 0", output.getvalue())
            self.assertNotIn("private comment body", output.getvalue())

    def test_invalid_input_has_sanitized_error(self):
        from hyperreview.publication import PublicationError
        output = io.StringIO()
        args = ["hyperreview", "publish-plan", "--bundle", "/private/preview",
                "--expected-preview-sha256", "a" * 64]
        with patch("sys.argv", args), contextlib.redirect_stderr(output), patch(
                "hyperreview.publication.plan_publication", side_effect=PublicationError("private detail")):
            self.assertEqual(main(), 1)
        self.assertIn("publication plan was not saved", output.getvalue())
        self.assertNotIn("private detail", output.getvalue())
