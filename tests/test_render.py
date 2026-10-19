import unittest

from hyperreview.model_contract import ContractError, prepare_request
from hyperreview.intake import digest
from hyperreview.render import render_preview, render_compact_preview
from test_model_contract import pack, valid_result


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.request = prepare_request(pack())
        self.result = valid_result(self.request)
        self.receipt = {"stage": "projections_validated",
                        "request_digest": self.request["request_digest"],
                        "compiler_sha256": "f" * 64}
        self.diff = {"version": "hypercode.diff/v1", "changes": [
            {"kind": "added", "node": "Application#App"}]}

    def render(self):
        self.receipt["result_digest"] = digest(self.result)
        return render_preview(self.request, self.result, self.receipt, self.diff).decode()

    def test_inference_scope_sources_and_structural_change_are_distinct(self):
        preview = self.render()
        self.assertIn("Status: **inferred**", preview)
        self.assertIn("not accepted architectural intent", preview)
        self.assertIn("Tree order is not execution order", preview)
        self.assertIn("blob/" + self.request["head_sha"], preview)
        self.assertIn("Tracking has not been confirmed", preview)
        self.assertIn(self.request["request_digest"], preview)

    def test_model_prose_cannot_inject_html_links_or_mentions(self):
        self.result["summary"] = '<script>alert(1)</script> [click](javascript:bad) @someone'
        preview = self.render()
        self.assertNotIn("<script>", preview)
        self.assertNotIn("[click](javascript:bad)", preview)
        self.assertNotIn("@someone", preview)
        self.assertIn("&lt;script&gt;", preview)

    def test_projection_uses_fence_longer_than_untrusted_content(self):
        self.result["after_hc"] = "Application#App\n```\n<script>bad</script>\n"
        self.assertIn("````hc\n", self.render())

    def test_compact_preview_has_diff_and_revision_links(self):
        self.receipt["result_digest"] = digest(self.result)
        preview = render_compact_preview(self.request, self.result, self.receipt, self.diff).decode()
        self.assertIn("```diff", preview)
        self.assertIn("blob/" + self.request["head_sha"], preview)
        self.assertIn("Ок или не ок", preview)
        self.assertIn("не означает порядок выполнения", preview)

    def test_historical_compact_preview_marks_publication_disabled(self):
        self.request["intake_mode"] = "historical_read_only"
        self.request["publication_allowed"] = False
        self.request["request_digest"] = "0" * 64
        unsigned = {key: value for key, value in self.request.items() if key != "request_digest"}
        from hyperreview import intake
        self.request["request_digest"] = intake.digest(unsigned)
        self.receipt["request_digest"] = self.request["request_digest"]
        self.result["request_digest"] = self.request["request_digest"]
        self.receipt["result_digest"] = digest(self.result)
        preview = render_compact_preview(self.request, self.result, self.receipt, self.diff).decode()
        self.assertIn("Исторический разбор, только локально; публикация отключена", preview)

    def test_compact_preview_escapes_prose_and_rejects_unbound_receipt(self):
        self.result["summary"] = "<script>bad</script> @someone"
        self.receipt["result_digest"] = digest(self.result)
        preview = render_compact_preview(self.request, self.result, self.receipt, self.diff).decode()
        self.assertNotIn("<script>", preview)
        self.assertNotIn("@someone", preview)
        self.receipt["stage"] = "model_generated"
        with self.assertRaises(ContractError):
            render_compact_preview(self.request, self.result, self.receipt, self.diff)

    def test_compact_preview_does_not_invent_changes(self):
        self.result["before_hc"] = self.result["after_hc"]
        self.receipt["result_digest"] = digest(self.result)
        preview = render_compact_preview(self.request, self.result, self.receipt, self.diff).decode()
        self.assertNotIn("```diff", preview)
        self.assertIn("Структурных изменений в проекции нет", preview)
        self.assertIn("Текущая проекция:\n```hc\n", preview)
        self.assertIn(self.result["after_hc"].rstrip(), preview)

    def test_unvalidated_or_unbound_receipt_is_rejected(self):
        for field, invalid in (("stage", "model_generated"), ("request_digest", "0" * 64)):
            with self.subTest(field=field):
                previous = self.receipt[field]
                self.receipt[field] = invalid
                with self.assertRaises(ContractError):
                    self.render()
                self.receipt[field] = previous


if __name__ == "__main__":
    unittest.main()
