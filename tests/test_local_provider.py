from dataclasses import replace
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time
import unittest

from hyperreview import intake, model_contract
from hyperreview.local_provider import ProviderConfig, ProviderError, generate


REPO = "0al-spec/SpecGraph"
BASE = "a" * 40
HEAD = "b" * 40


class SlowHeaders:
    def __init__(self, lines, body):
        self.lines = lines
        self.body = body


def make_request(content="def assess():\n    return True\n"):
    raw = content.encode("utf-8")
    record = {
        "side": "after", "revision": HEAD, "path": "src/assessment.py",
        "content": content, "content_sha256": hashlib.sha256(raw).hexdigest(),
        "content_bytes": len(raw), "line_start": 1,
        "line_end": content.count("\n") + int(not content.endswith("\n")),
        "trust": "untrusted_source_data", "url": "https://example.invalid/source",
    }
    evidence = {
        "schema": intake.SCHEMA, "stage": "evidence_collected",
        "repository": REPO, "pr": 17, "author": intake.AUTHOR,
        "authenticated_account": intake.AUTHOR, "base_repo": REPO, "head_repo": REPO,
        "state": "open", "draft": False, "base_sha": "c" * 40,
        "merge_base_sha": BASE, "head_sha": HEAD,
        "files": [{"before_path": None, "after_path": "src/assessment.py",
                    "sources": [record], "omissions": []}],
    }
    evidence["evidence_digest"] = intake.digest(evidence)
    return model_contract.prepare_request(evidence)


def make_plan(request):
    source_id = request["sources"][0]["id"]
    return {
        "schema": "hyperreview.composition-plan.v1",
        "request_digest": request["request_digest"],
        "nodes": [{"id": "assessment", "before_type": None, "after_type": "Assessment",
                   "before_parent": None, "after_parent": None, "before_refs": [],
                   "after_refs": [source_id], "reason": "It owns the assessment responsibility."}],
        "summary": "One assessment responsibility is proposed.",
        "limitations": ["The compiler must validate Hypercode syntax."],
    }


def make_result(request):
    from hyperreview.composition_plan import to_result
    return to_result(make_plan(request), request)


class FixtureServer:
    def __init__(self, callback):
        self.callback = callback
        self.requests = []
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                captured = {"path": self.path, "headers": dict(self.headers), "body": body}
                fixture.requests.append(captured)
                status, headers, response = fixture.callback(captured)
                if isinstance(response, SlowHeaders):
                    try:
                        reason = "OK" if status == 200 else "Redirect"
                        self.wfile.write(f"HTTP/1.1 {status} {reason}\r\n".encode())
                        self.wfile.flush()
                        for line, delay in response.lines:
                            time.sleep(delay)
                            self.wfile.write(line.encode() + b"\r\n")
                            self.wfile.flush()
                        self.wfile.write(response.body)
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                    return
                self.send_response(status)
                for key, value in headers.items():
                    self.send_header(key, value)
                self.end_headers()
                if response:
                    try:
                        if type(response) is list:
                            for delay, chunk in response:
                                time.sleep(delay)
                                self.wfile.write(chunk)
                                self.wfile.flush()
                        else:
                            self.wfile.write(response)
                            self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        pass

            def log_message(self, _format, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


class LocalProviderTests(unittest.TestCase):
    def setUp(self):
        self.request = make_request()
        self.config = None
        self.fixture = None

    def tearDown(self):
        if self.fixture is not None:
            self.fixture.close()

    def _envelope(self, config, result=None, *, include_usage=True, **overrides):
        result = result or make_plan(self.request)
        content = intake.encoded(result).decode("utf-8")
        if config.provider == "lmstudio":
            envelope = {
                "model": config.model,
                "choices": [{"message": {"role": "assistant", "content": content},
                             "finish_reason": "stop"}],
            }
            if include_usage:
                envelope["usage"] = {"prompt_tokens": 23, "completion_tokens": 11}
        else:
            envelope = {"model": config.model, "done": True, "done_reason": "stop",
                        "message": {"role": "assistant", "content": content}}
            if include_usage:
                envelope.update({"prompt_eval_count": 23, "eval_count": 11})
        envelope.update(overrides)
        return intake.encoded(envelope)

    def _start(self, provider="lmstudio", callback=None, **config_values):
        if callback is None:
            callback = lambda _request: (200, {"Content-Type": "application/json"},
                                         self._envelope(self.config))
        config_values.setdefault("context_tokens", 16384)
        self.fixture = FixtureServer(callback)
        prefix = "/v1" if provider == "lmstudio" else "/api"
        self.config = ProviderConfig(provider, f"http://127.0.0.1:{self.fixture.port}{prefix}",
                                     "fixture-model", **config_values)
        return self.fixture

    def test_lmstudio_wire_shape_receipt_and_token_counts(self):
        fixture = self._start()
        outcome = generate(self.request, self.config)
        self.assertEqual(outcome["result"], make_result(self.request))
        self.assertEqual(outcome["plan"], make_plan(self.request))
        self.assertEqual(outcome["receipt"]["provider_plan_digest"], intake.digest(outcome["plan"]))
        self.assertEqual(outcome["receipt"]["result_schema_sha256"],
                         intake.digest(model_contract.result_schema()))
        receipt = outcome["receipt"]
        self.assertEqual((receipt["provider"], receipt["model"]), ("lmstudio", "fixture-model"))
        self.assertEqual((receipt["input_tokens"], receipt["output_tokens"]), (23, 11))
        self.assertIsNone(receipt["model_revision"])
        self.assertGreaterEqual(receipt["elapsed_ms"], 0)
        self.assertNotIn("content", receipt)
        posted = fixture.requests[0]
        self.assertEqual(posted["path"], "/v1/chat/completions")
        self.assertNotIn("Authorization", posted["headers"])
        body = json.loads(posted["body"])
        self.assertEqual(body["model"], "fixture-model")
        self.assertFalse(body["stream"])
        self.assertEqual(body["temperature"], 0)
        self.assertEqual(body["max_tokens"], 1024)
        self.assertEqual(body["messages"][1]["content"], intake.encoded(self.request).decode())
        response_schema = body["response_format"]["json_schema"]
        self.assertTrue(response_schema["strict"])
        schema = response_schema["schema"]
        self.assertEqual(schema["properties"]["request_digest"]["const"], self.request["request_digest"])
        identity = schema["properties"]["nodes"]["items"]["properties"]
        self.assertEqual(list(identity)[0], "id")
        self.assertLess(list(identity).index("id"), list(identity).index("after_parent"))
        self.assertEqual(identity["before_refs"]["maxItems"], 0)
        self.assertEqual(identity["before_type"], {"type": "null"})
        self.assertEqual(identity["before_parent"], {"type": "null"})
        self.assertEqual(identity["after_refs"]["items"]["enum"], [self.request["sources"][0]["id"]])
        self.assertNotIn("claims", schema["properties"])
        self.assertNotIn("tools", body)

    def test_explicit_developer_role_is_transmitted_and_recorded(self):
        fixture = self._start(instruction_role="developer")
        outcome = generate(self.request, self.config)
        self.assertEqual(json.loads(fixture.requests[0]["body"])["messages"][0]["role"], "developer")
        self.assertEqual(outcome["receipt"]["instruction_role"], "developer")
        bad = replace(self.config, provider="ollama", instruction_role="developer")
        with self.assertRaises(ProviderError):
            generate(self.request, bad)
        self.assertEqual(len(fixture.requests), 1)

    def test_ollama_wire_shape_and_missing_counts_are_none(self):
        def callback(_request):
            return 200, {"Content-Type": "application/json"}, self._envelope(self.config, include_usage=False)

        fixture = self._start("ollama", callback=callback)
        outcome = generate(self.request, self.config)
        self.assertEqual(outcome["receipt"]["input_tokens"], None)
        self.assertEqual(outcome["receipt"]["output_tokens"], None)
        posted = fixture.requests[0]
        self.assertEqual(posted["path"], "/api/chat")
        body = json.loads(posted["body"])
        self.assertFalse(body["stream"])
        self.assertEqual(body["options"], {"temperature": 0, "num_predict": 1024, "num_ctx": 16384})
        self.assertEqual(body["keep_alive"], 0)
        self.assertIsInstance(body["format"], dict)
        self.assertNotIn("tools", body)

    def test_rejects_non_loopback_proxy_or_malformed_endpoint(self):
        endpoints = (
            "http://localhost:1234/v1", "http://example.com:1234/v1",
            "http://127.0.0.2:1234/v1", "http://user:pass@127.0.0.1:1234/v1",
            "http://127.0.0.1:1234/v1?x=1", "http://127.0.0.1:1234/v1#frag",
            "https://127.0.0.1:1234/v1", "http://127.0.0.1/v1",
            "http://[::1]:1234/api",
        )
        for endpoint in endpoints:
            with self.subTest(endpoint=endpoint), self.assertRaises(ProviderError):
                generate(self.request, ProviderConfig("lmstudio", endpoint, "m"))

    def test_rejects_invalid_config_types_and_bounds(self):
        bad_values = (
            {"provider": "cloud"}, {"model": ""}, {"context_tokens": True},
            {"context_tokens": 2047}, {"context_tokens": 131073}, {"max_tokens": 127},
            {"max_tokens": 4097}, {"timeout_seconds": 0}, {"timeout_seconds": 301},
            {"endpoint": "http://127.0.0.1:9999/v1/"},
        )
        for changes in bad_values:
            values = {"provider": "lmstudio", "endpoint": "http://127.0.0.1:1234/v1", "model": "m"}
            values.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ProviderError):
                generate(self.request, ProviderConfig(**values))

    def test_context_preflight_rejects_before_post(self):
        fixture = self._start(context_tokens=2048)
        with self.assertRaisesRegex(ProviderError, "context budget"):
            generate(self.request, self.config)
        self.assertEqual(fixture.requests, [])

    def test_rejects_redirect_and_non_200_without_following(self):
        fixture = self._start(callback=lambda _request: (302, {"Location": "http://example.com/"}, b""))
        with self.assertRaisesRegex(ProviderError, "HTTP 302"):
            generate(self.request, self.config)
        self.assertEqual(len(fixture.requests), 1)

    def test_rejects_oversize_response_without_reading_provider_text(self):
        fixture = self._start(callback=lambda _request: (
            200, {"Content-Length": str(1024 * 1024 + 1)}, b""))
        with self.assertRaisesRegex(ProviderError, "exceeds 1 MiB"):
            generate(self.request, self.config)
        self.assertEqual(len(fixture.requests), 1)

    def test_total_deadline_covers_response(self):
        def slow(_request):
            raw = self._envelope(self.config)
            chunks = [(0.35, raw[index:index + 256]) for index in range(0, len(raw), 256)]
            return 200, {"Content-Type": "application/json", "Content-Length": str(len(raw))}, chunks

        self._start(callback=slow, timeout_seconds=1)
        with self.assertRaisesRegex(ProviderError, "transport failed or timed out"):
            generate(self.request, self.config)

    def test_total_deadline_covers_slow_header_lines(self):
        def slow_headers(_request):
            raw = self._envelope(self.config)
            lines = [
                ("Content-Type: application/json", 0.35),
                (f"Content-Length: {len(raw)}", 0.35),
                ("Connection: close", 0.35),
                ("", 0.35),
            ]
            return 200, {}, SlowHeaders(lines, raw)

        self._start(callback=slow_headers, timeout_seconds=1)
        started = time.monotonic()
        with self.assertRaisesRegex(ProviderError, "transport failed or timed out"):
            generate(self.request, self.config)
        self.assertLess(time.monotonic() - started, 1.5)

    def test_rejects_malformed_duplicate_and_nonfinite_json(self):
        for raw in (b"{", b'{"model":"fixture-model","model":"other"}',
                    b'{"model":"fixture-model","x":NaN}'):
            self.fixture = None
            fixture = self._start(callback=lambda _request, raw=raw:
                                  (200, {"Content-Type": "application/json"}, raw))
            with self.subTest(raw=raw), self.assertRaises(ProviderError):
                generate(self.request, self.config)
            fixture.close()
            self.fixture = None

        for content in ('{"x":1,"x":2}', '{"x":NaN}'):
            result_envelope = {
                "model": "fixture-model",
                "choices": [{"message": {"role": "assistant", "content": content},
                             "finish_reason": "stop"}],
            }
            fixture = self._start(callback=lambda _request, envelope=result_envelope:
                                  (200, {"Content-Type": "application/json"}, intake.encoded(envelope)))
            with self.subTest(content=content), self.assertRaisesRegex(ProviderError, "content is invalid JSON"):
                generate(self.request, self.config)
            fixture.close()
            self.fixture = None

    def test_rejects_wrong_model_tool_calls_truncation_and_ollama_not_done(self):
        cases = (
            ("lmstudio", lambda: {"model": "wrong", "choices": []}),
            ("lmstudio", lambda: {"model": "fixture-model", "choices": [{"finish_reason": "length", "message": {"role": "assistant", "content": "{}"}}]}),
            ("lmstudio", lambda: {"model": "fixture-model", "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "{}", "tool_calls": [{"id": "x"}]}}]}),
            ("ollama", lambda: {"model": "fixture-model", "done": False, "message": {"content": "{}"}}),
            ("ollama", lambda: {"model": "fixture-model", "done": True, "done_reason": "length", "message": {"role": "assistant", "content": "{}"}}),
            ("ollama", lambda: {"model": "fixture-model", "done": True, "done_reason": "stop", "message": {"role": "assistant", "content": "{}", "tool_calls": [{"id": "x"}]}}),
            ("ollama", lambda: {"model": "fixture-model", "done": True, "done_reason": "stop", "message": {"role": "user", "content": "{}"}}),
        )
        for provider, envelope in cases:
            self.fixture = None
            self.config = None
            fixture = self._start(provider, callback=lambda _request, envelope=envelope:
                                  (200, {"Content-Type": "application/json"}, intake.encoded(envelope())))
            with self.subTest(provider=provider, envelope=envelope), self.assertRaises(ProviderError):
                generate(self.request, self.config)
            fixture.close()
            self.fixture = None

    def test_rejects_invalid_result_binding_and_unknown_fields(self):
        wrong_digest = make_plan(self.request)
        wrong_digest["request_digest"] = "0" * 64
        unknown = make_plan(self.request)
        unknown["authority"] = "elevated"
        invalid_type = make_plan(self.request)
        invalid_type["nodes"][0]["after_type"] = "PredicateSpec[Context]"
        for result in (wrong_digest, unknown, invalid_type, make_result(self.request)):
            self.fixture = None
            fixture = self._start(callback=lambda _request, result=result:
                                  (200, {"Content-Type": "application/json"},
                                   self._envelope(self.config, result=result)))
            with self.assertRaisesRegex(ProviderError, "failed local validation"):
                generate(self.request, self.config)
            fixture.close()
            self.fixture = None

    def test_rejects_request_that_fails_local_validation_before_post(self):
        fixture = self._start()
        tampered = dict(self.request)
        tampered["request_digest"] = "0" * 64
        with self.assertRaisesRegex(ProviderError, "failed local validation"):
            generate(tampered, self.config)
        self.assertEqual(fixture.requests, [])

    def test_rejects_rehashed_sensitive_source_before_post(self):
        fixture = self._start()
        tampered = json.loads(intake.encoded(self.request))
        source = tampered["sources"][0]
        source["content"] = 'password: "sensitive-value-123"\n'
        source["content_sha256"] = hashlib.sha256(source["content"].encode()).hexdigest()
        source["id"] = "src_" + hashlib.sha256(intake.encoded([
            source["revision"], source["path"], source["content_sha256"]])).hexdigest()
        tampered["source_selection"]["included_source_bytes"] = len(intake.encoded(source["content"]))
        unsigned = {key: value for key, value in tampered.items() if key != "request_digest"}
        tampered["request_digest"] = intake.digest(unsigned)
        with self.assertRaisesRegex(ProviderError, "failed local validation"):
            generate(tampered, self.config)
        self.assertEqual(fixture.requests, [])


if __name__ == "__main__":
    unittest.main()
