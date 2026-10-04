import hashlib
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

from hyperreview import intake, model_contract
from hyperreview.codex_provider import CodexConfig, CodexError, generate, _decode_events


REPO = "0al-spec/SpecGraph"
BASE = "a" * 40
HEAD = "b" * 40


def make_request(*, paired=False):
    files = []
    sources = []
    for side, revision in (("before", BASE), ("after", HEAD)):
        if side == "before" and not paired:
            continue
        content = "def assess():\n    return True\n" if side == "before" else \
            "def assess():\n    return False\n" if paired else "def assess():\n    return True\n"
        raw = content.encode()
        sources.append({
            "side": side, "revision": revision, "path": "src/assessment.py",
            "content": content, "content_sha256": hashlib.sha256(raw).hexdigest(),
            "content_bytes": len(raw), "line_start": 1, "line_end": 2,
            "trust": "untrusted_source_data", "url": "https://example.invalid/source",
        })
    files.append({"before_path": "src/assessment.py" if paired else None,
                  "after_path": "src/assessment.py", "sources": sources, "omissions": []})
    evidence = {
        "schema": intake.SCHEMA, "stage": "evidence_collected",
        "repository": REPO, "pr": 17, "author": intake.AUTHOR,
        "authenticated_account": intake.AUTHOR, "base_repo": REPO, "head_repo": REPO,
        "state": "open", "draft": False, "base_sha": "c" * 40,
        "merge_base_sha": BASE, "head_sha": HEAD, "files": files,
    }
    evidence["evidence_digest"] = intake.digest(evidence)
    return model_contract.prepare_request(evidence)


def make_plan(request, *, valid=True, bound=True):
    before = [source["id"] for source in request["sources"] if source["side"] == "before"]
    after = [source["id"] for source in request["sources"] if source["side"] == "after"]
    return {
        "schema": "hyperreview.composition-plan.v1",
        "request_digest": request["request_digest"] if bound else "0" * 64,
        "nodes": [{"id": "assessment", "before_type": "Assessment" if before else None,
                   "after_type": "Assessment", "before_parent": None, "after_parent": None,
                   "before_refs": before if valid else [], "after_refs": after if valid else [],
                   "reason": "The assessment responsibility is represented by the supplied code."}],
        "summary": "The assessment responsibility is represented by the supplied code.",
        "limitations": ["Only the supplied source records were considered."],
    }


def fake_cli(root, request, mode="success"):
    root.mkdir(parents=True, exist_ok=True)
    plan = make_plan(request)
    invalid = make_plan(request, valid=False)
    unbound = make_plan(request, bound=False)
    source = f'''#!{sys.executable}
import json, os, pathlib, sys, time
args = sys.argv[1:]
root = pathlib.Path({str(root)!r})
cwd = pathlib.Path.cwd()
schema = pathlib.Path(args[args.index("--output-schema") + 1])
output = pathlib.Path(args[args.index("--output-last-message") + 1])
count_path = cwd / ".calls"
count = int(count_path.read_text()) + 1 if count_path.exists() else 1
count_path.write_text(str(count))
(root / f"prompt-{{count}}.txt").write_text(sys.stdin.read())
(root / f"args-{{count}}.json").write_text(json.dumps(args))
(root / f"cwd-{{count}}.txt").write_text(str(cwd))
(root / f"schema-{{count}}.json").write_bytes(schema.read_bytes())
valid = json.loads({json.dumps(plan)!r})
invalid = json.loads({json.dumps(invalid)!r})
unbound = json.loads({json.dumps(unbound)!r})
mode = {mode!r}
if mode == "timeout":
    if hasattr(os, "fork"):
        child = os.fork()
        if child == 0:
            time.sleep(30)
            os._exit(0)
    time.sleep(30)
if mode == "overflow":
    sys.stdout.write("x" * (1024 * 1024 + 100))
    sys.stdout.flush()
    time.sleep(5)
    sys.exit(0)
if mode == "nonzero":
    sys.stderr.write("private provider details")
    sys.exit(3)
if mode == "stderr-warning":
    sys.stderr.write("benign CLI warning\\n")
if mode == "malformed":
    print("{{not-json")
    sys.exit(0)
if mode == "provider-error":
    print(json.dumps({{"type":"error", "message":"private provider details"}}))
    sys.exit(0)
if mode == "unexpected-tool":
    plan_value = valid
    item_type = "command_execution"
elif mode == "two-invalid":
    plan_value = invalid
    item_type = "agent_message"
elif mode == "unbound":
    plan_value = unbound
    item_type = "agent_message"
elif mode == "missing-output":
    plan_value = valid
    item_type = "agent_message"
else:
    plan_value = invalid if mode == "repair" and count == 1 else valid
    item_type = "agent_message"
text = json.dumps(plan_value, separators=(",", ":"), ensure_ascii=False)
if mode == "symlink-output":
    target = root / "external.json"
    target.write_text(text)
    output.symlink_to(target)
elif mode == "huge-output":
    output.write_bytes(b"x" * (1024 * 1024 + 1))
elif mode != "missing-output":
    output.write_text(text)
item = {{"type": item_type, "text": text}}
print(json.dumps({{"type":"thread.started", "thread_id":"fake-thread"}}))
print(json.dumps({{"type":"turn.started"}}))
print(json.dumps({{"type":"item.completed", "item":item}}))
print(json.dumps({{"type":"turn.completed", "usage":{{"input_tokens":23,"output_tokens":11}}}}))
'''
    executable = root / "fake-codex"
    executable.write_text(source)
    executable.chmod(0o700)
    return executable


class CodexProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.request = make_request()
        self.executable = fake_cli(self.root / "capture", self.request)

    def tearDown(self):
        self.temp.cleanup()

    def config(self, *, timeout=5, mode=None):
        executable = self.executable
        if mode is not None:
            executable = fake_cli(self.root / ("capture-" + mode), self.request, mode)
        return CodexConfig(executable=str(executable), timeout_seconds=timeout)

    def test_exact_disabled_host_startup_notice_is_bounded(self):
        notice = {"type": "item.completed", "item": {
            "id": "item_0", "type": "error",
            "message": "Code Mode is unavailable because code-mode host is disabled. "
                       "Code mode will fail closed; enable `features.code_mode_host` "
                       "and install `codex-code-mode-host`."}}
        events = [
            {"type": "thread.started", "thread_id": "private-thread"}, notice,
            {"type": "turn.started"},
            {"type": "item.completed", "item": {"type": "agent_message", "text": "{}"}},
            {"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 2}},
        ]
        def decode(values):
            return _decode_events("\n".join(json.dumps(value) for value in values).encode())
        self.assertEqual(decode(events), ("{}", (1, 2), True))
        altered = deepcopy(notice)
        altered["item"]["message"] += " changed"
        extra = deepcopy(notice)
        extra["item"]["tool"] = "unexpected"
        invalid = [
            [notice, *events[2:]],
            [events[0], notice, notice, *events[2:]],
            [events[0], events[2], notice, *events[3:]],
            [events[0], altered, *events[2:]],
            [events[0], extra, *events[2:]],
            [*events[:3], {"type": "item.completed", "item": {"type": "command_execution"}}, *events[3:]],
            [*events[:2], events[0], *events[2:]],
            [*events[:2], events[3], events[4], events[2]],
            [events[0], events[2], events[4], events[3]],
        ]
        for case in invalid:
            with self.subTest(case=case), self.assertRaises(CodexError):
                decode(case)

    def test_success_binds_result_receipt_and_private_prompt(self):
        generated = generate(self.request, self.config())
        self.assertEqual(set(generated), {"result", "plan", "receipt"})
        self.assertEqual(generated["receipt"]["provider"], "codex")
        self.assertEqual(generated["receipt"]["instruction_role"], "cli_prompt")
        self.assertEqual(generated["receipt"]["input_tokens"], 23)
        self.assertEqual(generated["receipt"]["output_tokens"], 11)
        self.assertEqual(generated["receipt"]["attempt_count"], 1)
        args = json.loads((self.root / "capture" / "args-1.json").read_text())
        for expected in ("--ignore-user-config", "--ephemeral", "--skip-git-repo-check",
                         "--sandbox", "read-only", "--model", "gpt-6-luna", "--json"):
            self.assertIn(expected, args)
        disabled = [args[index + 1] for index, item in enumerate(args[:-1]) if item == "--disable"]
        self.assertEqual(len(disabled), 18)
        self.assertTrue({"code_mode", "code_mode_only", "code_mode_host"}.issubset(disabled))
        self.assertIn("--output-schema", args)
        prompt = (self.root / "capture" / "prompt-1.txt").read_text()
        self.assertIn(intake.encoded(self.request).decode(), prompt)
        cwd = (self.root / "capture" / "cwd-1.txt").read_text()
        self.assertNotEqual(cwd, str(self.root))
        schema = json.loads((self.root / "capture" / "schema-1.json").read_text())
        self.assertNotIn("uniqueItems", json.dumps(schema))

    def test_stderr_warning_does_not_corrupt_event_jsonl(self):
        executable = fake_cli(self.root / "stderr-capture", self.request, "stderr-warning")
        generated = generate(self.request, CodexConfig(executable=str(executable), timeout_seconds=5))
        self.assertEqual(generated["receipt"]["attempt_count"], 1)

    def test_comparison_precedes_complete_request_in_untrusted_prompt(self):
        request = make_request(paired=True)
        executable = fake_cli(self.root / "paired-capture", request)
        generate(request, CodexConfig(executable=str(executable), timeout_seconds=5))
        prompt = (self.root / "paired-capture" / "prompt-1.txt").read_text()
        comparison = prompt.index("Сравнительные данные")
        original = prompt.index("Полный исходный запрос")
        self.assertLess(comparison, original)
        self.assertIn("same_path_diffs", prompt)
        self.assertIn(intake.encoded(request).decode(), prompt)

    def test_one_invalid_plan_gets_one_fresh_bounded_repair(self):
        executable = fake_cli(self.root / "repair-capture", self.request, "repair")
        generated = generate(self.request, CodexConfig(executable=str(executable), timeout_seconds=5))
        self.assertEqual(generated["receipt"]["attempt_count"], 2)
        self.assertEqual(generated["receipt"]["repair_errors"], ["missing_refs"])
        self.assertIn("Ошибка missing_refs", (self.root / "repair-capture" / "prompt-2.txt").read_text())

    def test_second_invalid_plan_fails_with_safe_issue_code(self):
        executable = fake_cli(self.root / "invalid-capture", self.request, "two-invalid")
        with self.assertRaisesRegex(CodexError, "issue codes: missing_refs, missing_refs"):
            generate(self.request, CodexConfig(executable=str(executable), timeout_seconds=5))

    def test_timeout_kills_process_group(self):
        executable = fake_cli(self.root / "timeout-capture", self.request, "timeout")
        with self.assertRaisesRegex(CodexError, "timed out"):
            generate(self.request, CodexConfig(executable=str(executable), timeout_seconds=1))

    def test_combined_output_overflow_is_bounded(self):
        executable = fake_cli(self.root / "overflow-capture", self.request, "overflow")
        with self.assertRaisesRegex(CodexError, "output exceeds 1 MiB"):
            generate(self.request, CodexConfig(executable=str(executable), timeout_seconds=5))

    def test_rejects_tool_nonzero_malformed_and_missing_output(self):
        for mode, expected in (("unexpected-tool", "tool action"), ("nonzero", "unsuccessfully"),
                               ("malformed", "malformed JSONL"),
                               ("provider-error", "unexpected event"),
                               ("missing-output", "unavailable"),
                               ("symlink-output", "regular, non-symlink"),
                               ("huge-output", "exceeds 1 MiB")):
            with self.subTest(mode=mode):
                executable = fake_cli(self.root / ("capture-" + mode), self.request, mode)
                with self.assertRaisesRegex(CodexError, expected):
                    generate(self.request, CodexConfig(executable=str(executable), timeout_seconds=5))

    def test_rejects_unbound_plan_and_untrusted_cli_config(self):
        executable = fake_cli(self.root / "unbound-capture", self.request, "unbound")
        with self.assertRaisesRegex(CodexError, "issue codes: schema_or_binding"):
            generate(self.request, CodexConfig(executable=str(executable), timeout_seconds=5))
        with self.assertRaisesRegex(CodexError, "config has an invalid type"):
            generate(self.request, object())


if __name__ == "__main__":
    unittest.main()
