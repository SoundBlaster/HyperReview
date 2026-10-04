import contextlib
import io
from pathlib import Path
import unittest
from unittest.mock import patch

from hyperreview.__main__ import main


class FeedbackCliTests(unittest.TestCase):
    def test_cli_passes_local_assessment_without_printing_note(self):
        output = io.StringIO()
        arguments = ["hyperreview", "feedback", "--bundle", "/private/preview", "--assessment", "not_ok",
                     "--note", "private note", "--expected-preview-sha256", "a" * 64]
        with patch("sys.argv", arguments), contextlib.redirect_stdout(output), patch(
                "hyperreview.feedback.save_feedback", return_value=Path("/private/feedback/id")) as save:
            self.assertEqual(main(), 0)
        self.assertEqual(save.call_args.args, (Path("/private/preview"), "not_ok"))
        self.assertEqual(save.call_args.kwargs["note"], "private note")
        self.assertEqual(save.call_args.kwargs["expected_preview_sha256"], "a" * 64)
        self.assertNotIn("private note", output.getvalue())
        self.assertIn("feedback.json", output.getvalue())

    def test_failed_capture_reports_no_record_without_exception_body(self):
        from hyperreview.feedback import FeedbackError
        error = io.StringIO()
        arguments = ["hyperreview", "feedback", "--bundle", "/private/preview", "--assessment", "ok"]
        with patch("sys.argv", arguments), contextlib.redirect_stderr(error), patch(
                "hyperreview.feedback.save_feedback", side_effect=FeedbackError("sensitive detail")):
            self.assertEqual(main(), 1)
        self.assertIn("feedback was not saved", error.getvalue())
        self.assertNotIn("sensitive detail", error.getvalue())
