import os
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from hyperreview.codex_isolation import Boundary, IsolationError, native_executable, profile, isolated
from hyperreview.codex_provider import CodexConfig, CodexError, generate
from test_codex_provider import make_request, make_plan


class IsolationTests(unittest.TestCase):
    def test_invalid_ports_and_wrappers_fail_closed(self):
        for port in (True, 0, 65536, "443"):
            with self.subTest(port=port), self.assertRaises(IsolationError):
                profile(Path("/binary"), Path("/work"), Path("/work/protected"), Path("/auth"), port)
        with tempfile.TemporaryDirectory() as temp:
            wrapper = Path(temp)/"codex"
            wrapper.write_text("#!/bin/sh\nexit 0\n")
            wrapper.chmod(0o700)
            with self.assertRaises(IsolationError):
                native_executable(wrapper)

    def test_no_silent_fallback_on_other_platform(self):
        with patch("hyperreview.codex_isolation.sys.platform", "linux"), self.assertRaises(IsolationError):
            with isolated(Path("/binary"), Path("/work"), time.monotonic()+5):
                self.fail("unsupported isolation entered")

    def test_environment_policy_and_private_login(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve(); work=root/"work"; work.mkdir()
            login=root/"login"; login.mkdir(); auth=login/"auth.json"
            auth.write_text('{"synthetic":true}'); auth.chmod(0o600)
            with patch.dict(os.environ, {"CODEX_HOME":str(login),"GH_TOKEN":"canary", "OPENAI_API_KEY":"canary", "HTTPS_PROXY":"http://untrusted"}), \
                    patch("hyperreview.codex_isolation.SYSTEM_CA") as ca:
                ca.lstat.return_value=type("Metadata",(),{"st_mode":0o100644,"st_uid":0,"st_size":10})()
                ca.read_bytes.return_value=b"public-ca"
                boundary=Boundary(Path("/trusted/codex"),work,12345)
            self.assertNotIn("GH_TOKEN",boundary.environment)
            self.assertNotIn("OPENAI_API_KEY",boundary.environment)
            self.assertEqual(boundary.environment["HTTPS_PROXY"],"http://127.0.0.1:12345")
            text=boundary.policy.read_text()
            self.assertIn('(deny default)',text)
            self.assertNotIn('(subpath "/System")',text)
            self.assertTrue((Path(boundary.environment["CODEX_HOME"])/"auth.json").is_symlink())
            self.assertEqual(boundary.wrap(["/trusted/codex"])[0],"/usr/bin/sandbox-exec")
            self.assertEqual(auth.read_text(),'{"synthetic":true}')
            auth.chmod(0o644)
            other=root/"other";other.mkdir()
            with patch.dict(os.environ,{"CODEX_HOME":str(login)}), \
                    patch("hyperreview.codex_isolation.SYSTEM_CA") as ca, self.assertRaises(IsolationError):
                ca.lstat.return_value=type("Metadata",(),{"st_mode":0o100644,"st_uid":0,"st_size":10})()
                Boundary(Path("/trusted/codex"),other,12345)

    def test_isolation_rejects_fake_cli_before_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            wrapper=Path(temp)/"codex";wrapper.write_text("#!/bin/sh\nexit 0\n");wrapper.chmod(0o700)
            with self.assertRaises(CodexError):
                generate(make_request(),CodexConfig(executable=str(wrapper),allow_cloud_source=True,isolate_process=True))

    @unittest.skipUnless(sys.platform=="darwin" and shutil.which("cc"),"macOS native adapter probe")
    def test_generation_wraps_inventory_and_exec_and_records_isolation(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve(); login=root/"login";login.mkdir()
            auth=login/"auth.json";auth.write_text('{"synthetic":true}');auth.chmod(0o600)
            request=make_request(); plan=json.dumps(make_plan(request),separators=(",",":"))
            events="\n".join(json.dumps(event) for event in (
                {"type":"thread.started"}, {"type":"turn.started"},
                {"type":"item.completed","item":{"type":"agent_message","text":plan}},
                {"type":"turn.completed"}))+"\n"
            source=root/"stub.c";binary=root/"stub"
            source.write_text('#include <stdio.h>\n#include <string.h>\nint main(int n,char **v){'
                'if(n==3 && !strcmp(v[1],"features")){puts("view_image stable false");return 0;}'
                'for(int i=1;i+1<n;i++)if(!strcmp(v[i],"--output-last-message")){'
                'FILE *f=fopen(v[i+1],"w");if(!f)return 2;fputs('+json.dumps(plan)+',f);fclose(f);}'
                'fputs('+json.dumps(events)+',stdout);return 0;}')
            subprocess.run([shutil.which("cc"),str(source),"-o",str(binary)],check=True,capture_output=True,timeout=30)
            with patch.dict(os.environ,{"CODEX_HOME":str(login),"GH_TOKEN":"canary"}):
                result=generate(request,CodexConfig(executable=str(binary),allow_cloud_source=True,
                    isolate_process=True,timeout_seconds=10))
            self.assertEqual(result["receipt"]["process_isolation"]["mode"],"macos-seatbelt-v1")
            self.assertEqual(result["receipt"]["attempt_count"],1)
            self.assertEqual(result["plan"],make_plan(request))

    @unittest.skipUnless(sys.platform=="darwin" and shutil.which("cc"),"macOS native boundary probe")
    def test_native_syscalls_are_denied_with_positive_controls(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();work=root/"work";work.mkdir()
            binary=root/"probe"
            source=Path(__file__).parent/"fixtures/isolation_probe.c"
            subprocess.run([shutil.which("cc"),str(source),"-o",str(binary)],check=True,capture_output=True,timeout=30)
            inside=work/"inside";inside.write_text("inside")
            outside=root/"outside";outside.write_text("outside")
            (work/"outside-link").symlink_to(outside)
            login=root/"login";login.mkdir();auth=login/"auth.json"
            auth.write_text('{"synthetic":true}');auth.chmod(0o600)
            with tempfile.TemporaryDirectory(prefix="hr-socket-", dir="/tmp") as socket_root, \
                    socket.socket() as allowed, socket.socket() as forbidden, socket.socket(socket.AF_UNIX) as unix:
                allowed.bind(("127.0.0.1",0));allowed.listen()
                forbidden.bind(("127.0.0.1",0));forbidden.listen()
                unix_path=str(Path(socket_root)/"canary.sock");unix.bind(unix_path);unix.listen()
                with patch.dict(os.environ,{"CODEX_HOME":str(login)}):
                    boundary=Boundary(binary,work,allowed.getsockname()[1])
                command=boundary.wrap([str(binary),str(inside),str(outside),str(boundary.policy),str(auth),
                    str(allowed.getsockname()[1]),str(forbidden.getsockname()[1]),unix_path,
                    str(Path(boundary.environment["CODEX_HOME"])/"auth.json")])
                result=subprocess.run(command,cwd=work,env=boundary.environment,capture_output=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr.decode())
            self.assertIn(b"fork and shell denied",result.stdout)
            self.assertEqual(outside.read_text(),"outside")
            self.assertEqual(auth.read_text(),'{"synthetic":true}')
