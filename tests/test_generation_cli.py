import contextlib
import io
from pathlib import Path
import unittest
from unittest.mock import patch

from hyperreview.__main__ import main
from test_local_provider import make_request, make_plan, make_result


class GenerationCLITests(unittest.TestCase):
    def invoke(self, arguments, provider="codex"):
        request = make_request()
        proposed = {"plan": make_plan(request), "result": make_result(request),
                    "receipt": {"provider": provider, "model": "gpt-6-luna"}}
        module = "hyperreview.codex_provider" if provider == "codex" else "hyperreview.local_provider"
        with patch("sys.argv", ["hyperreview", "generate", "--request", "/private/request.json", *arguments]), \
                patch("hyperreview.__main__.read_json", return_value=request), \
                patch(module + ".generate", return_value=proposed) as generate, \
                patch("hyperreview.__main__.write_bundle", return_value=Path("/private/bundle")) as write, \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            status = main()
        return status, generate, write

    def test_default_generation_uses_codex_luna_low_and_standard_bundle(self):
        status, generate, write = self.invoke([])
        self.assertEqual(status, 0)
        config = generate.call_args.args[1]
        self.assertEqual(config.model, "gpt-6-luna")
        self.assertEqual(config.reasoning_effort, "low")
        artifacts = write.call_args.args[0]
        self.assertEqual(set(artifacts), {"request.json", "composition-plan.json", "result.json", "receipt.json"})
        import json
        receipt = json.loads(artifacts["receipt.json"])
        self.assertEqual(receipt["provider"], "codex")
        self.assertEqual(receipt["stage"], "model_generated")
        self.assertEqual(receipt["hypercode_validation"], "not_started")

    def test_explicit_codex_operator_settings_are_forwarded(self):
        _, generate, _ = self.invoke(["--model", "gpt-6-luna", "--reasoning-effort", "high",
                                     "--codex-executable", "/trusted/codex", "--timeout-seconds", "90"])
        config = generate.call_args.args[1]
        self.assertEqual(config.reasoning_effort, "high")
        self.assertEqual(config.executable, "/trusted/codex")
        self.assertEqual(config.timeout_seconds, 90)

    def test_http_requires_explicit_model_and_preserves_its_defaults(self):
        _, generate, _ = self.invoke(["--provider", "lmstudio", "--model", "local-model"], "lmstudio")
        config = generate.call_args.args[1]
        self.assertEqual((config.model, config.context_tokens, config.max_tokens, config.instruction_role),
                         ("local-model", 8192, 1024, "system"))
        with self.assertRaises(SystemExit):
            self.invoke(["--provider", "lmstudio"], "lmstudio")

    def test_provider_specific_options_are_rejected_instead_of_ignored(self):
        for arguments, provider in ((["--max-tokens", "1024"], "codex"),
                                    (["--context-tokens", "8192"], "codex"),
                                    (["--endpoint", "http://127.0.0.1:1234/v1"], "codex"),
                                    (["--instruction-role", "developer"], "codex"),
                                    (["--provider", "ollama", "--model", "m", "--reasoning-effort", "low"], "ollama"),
                                    (["--provider", "lmstudio", "--model", "m", "--codex-executable", "/x"], "lmstudio")):
            with self.subTest(arguments=arguments), self.assertRaises(SystemExit):
                self.invoke(arguments, provider)
