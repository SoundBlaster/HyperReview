import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import hyperreview.__main__ as cli
from hyperreview.tracking import TrackingError


class TrackingPreviewCliTests(unittest.TestCase):
    def invoke(self, bundle, *patches):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch("sys.argv", ["hyperreview", "track", "--bundle", str(bundle)]))
            stack.enter_context(contextlib.redirect_stdout(stdout))
            stack.enter_context(contextlib.redirect_stderr(stderr))
            for target, replacement in patches:
                stack.enter_context(mock.patch(target, replacement))
            status = cli.main()
        return status, stdout.getvalue(), stderr.getvalue()

    def test_confirmed_tracking_with_compact_symlink_keeps_verbose_preview_and_reports_refresh_incomplete(self):
        with tempfile.TemporaryDirectory(prefix="tracking-preview-cli-") as temporary:
            bundle = Path(temporary) / "bundle"
            bundle.mkdir()
            verbose_preview = bundle / "preview.md"
            verbose_preview.write_bytes(b"existing verbose preview")
            compact_preview = bundle / "preview-compact.md"
            compact_preview.symlink_to(Path(temporary) / "outside.md")

            event = {"correlation_id": "event"}
            receipt = {"run_id": "run-123", "trace_id": "trace-456"}
            update = mock.Mock(side_effect=[event, {**event, "receipt": receipt}])
            reconcile = mock.Mock(return_value=receipt)
            reads = mock.Mock(side_effect=lambda path, **kwargs: {"loaded": Path(path).name})
            render_verbose = mock.Mock(return_value=b"refreshed verbose preview")
            render_compact = mock.Mock(return_value=b"refreshed compact preview")

            status, stdout, stderr = self.invoke(bundle, (
                "hyperreview.tracking.update_bundle_tracking", update), (
                "hyperreview.tracking.reconcile", reconcile), (
                "hyperreview.__main__.read_json", reads), (
                "hyperreview.render.render_preview", render_verbose), (
                "hyperreview.render.render_compact_preview", render_compact),
            )

            self.assertEqual(status, 1)
            self.assertIn("tracking confirmed; preview refresh incomplete", stderr)
            self.assertNotIn("tracking remains pending", stderr)
            self.assertEqual(update.call_count, 2)
            reconcile.assert_called_once()
            render_verbose.assert_called_once()
            render_compact.assert_not_called()
            self.assertEqual(verbose_preview.read_bytes(), b"existing verbose preview")
            self.assertTrue(compact_preview.is_symlink())

    def test_failure_before_reconciliation_reports_tracking_remains_pending(self):
        with tempfile.TemporaryDirectory(prefix="tracking-preview-pending-") as temporary:
            bundle = Path(temporary) / "bundle"
            bundle.mkdir()
            update = mock.Mock(side_effect=TrackingError("bundle update failed"))
            reconcile = mock.Mock()
            status, stdout, stderr = self.invoke(bundle, (
                "hyperreview.tracking.update_bundle_tracking", update), (
                "hyperreview.tracking.reconcile", reconcile),
            )

            self.assertEqual(status, 1)
            self.assertIn("tracking remains pending", stderr)
            self.assertNotIn("preview refresh incomplete", stderr)
            reconcile.assert_not_called()
            update.assert_called_once_with(bundle)


if __name__ == "__main__":
    unittest.main()
