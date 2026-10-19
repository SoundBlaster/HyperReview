"""Outer macOS process boundary; distinct from Codex's command sandbox.

Only the native CLI, system runtime, job workspace and read-only login are
readable. All egress must pass the supervised CONNECT proxy. Unsupported
platforms, wrappers and missing credentials fail closed.
"""

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import platform
import stat
import sys


MAX_NATIVE_BYTES = 512 * 1024 * 1024
SANDBOX = Path("/usr/bin/sandbox-exec")
SYSTEM_CA = Path("/private/etc/ssl/cert.pem")
_MACHO = (b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca")


class IsolationError(Exception):
    """The outer process boundary cannot be established."""


def native_executable(path):
    """Resolve the known npm launcher without ever executing Node or its script."""
    path = Path(path).resolve(strict=True)
    if path.name == "codex.js" and path.parent.name == "bin":
        target = {"arm64": "aarch64", "x86_64": "x86_64"}.get(platform.machine())
        if target is None:
            raise IsolationError("Unsupported native Codex architecture")
        package = f"codex-darwin-{'arm64' if target == 'aarch64' else 'x64'}"
        path = (path.parent.parent / "node_modules/@openai" / package /
                f"vendor/{target}-apple-darwin/bin/codex").resolve(strict=True)
    metadata = path.lstat()
    if (not stat.S_ISREG(metadata.st_mode) or not metadata.st_mode & 0o111
            or metadata.st_size > MAX_NATIVE_BYTES):
        raise IsolationError("Isolation requires a native Codex executable within 512 MiB")
    with path.open("rb") as source:
        if source.read(4) not in _MACHO:
            raise IsolationError("Isolation requires a native Mach-O Codex executable")
    return path


def profile(executable, workdir, protected, auth, proxy_port):
    """Use literal paths with JSON escaping; no model-controlled policy fragments."""
    if type(proxy_port) is not int or not 1 <= proxy_port <= 65535:
        raise IsolationError("Invalid isolation proxy port")
    q = lambda value: json.dumps(str(value), ensure_ascii=True)
    # /System itself would include /System/Volumes/Data. Allow runtime subtrees
    # individually, never the entire system or Homebrew prefix.
    # Seatbelt default does not cover every operation class: explicitly restrict
    # process inspection, executable mappings, IOKit properties and NVRAM too.
    return f'''(version 1)
(deny default)
(deny file-map-executable iokit-get-properties process-info* nvram*)
(deny dynamic-code-generation)
(allow process-info* (target self))
(allow file-map-executable
  (literal {q(executable)}) (subpath "/System/Library")
  (subpath "/System/Cryptexes") (subpath "/System/Volumes/Preboot/Cryptexes")
  (subpath "/usr/lib"))
(deny sysctl-read (sysctl-name-prefix "kern.proc"))
(allow sysctl-read
  (sysctl-name-prefix "hw.")
  (sysctl-name "kern.ostype" "kern.osrelease" "kern.osversion"
    "kern.osproductversion" "kern.argmax" "kern.maxfilesperproc"
    "kern.maxprocperuid" "sysctl.proc_translated"))
(allow file-read-metadata)
(allow file-read* (literal "/")
  (subpath "/System/Library") (subpath "/System/Cryptexes")
  (subpath "/System/Volumes/Preboot/Cryptexes")
  (subpath "/usr/lib") (subpath "/usr/share")
  (literal "/private/etc/ssl/cert.pem")
  (literal "/dev/random") (literal "/dev/urandom") (literal "/dev/null"))
(allow file-write-data (literal "/dev/null"))
(allow file-read* (literal {q(executable)}) (literal {q(auth)}))
(allow file-read* file-write* (subpath {q(workdir)}))
(deny file-write* (subpath {q(protected)}) (literal {q(workdir / "codex/auth.json")}))
(allow process-exec (literal {q(executable)}))
(allow network-outbound (remote tcp "localhost:{proxy_port}"))
'''


class Boundary:
    def __init__(self, executable, workdir, proxy_port):
        ca_metadata = SYSTEM_CA.lstat()
        if (not stat.S_ISREG(ca_metadata.st_mode) or ca_metadata.st_uid != 0
                or ca_metadata.st_mode & 0o022 or ca_metadata.st_size > 1024 * 1024):
            raise IsolationError("Isolation requires the trusted system CA bundle")
        self.workdir = workdir.resolve(strict=True)
        protected = self.workdir / ".isolation"
        protected.mkdir(mode=0o700)
        home = self.workdir / "home"
        home.mkdir(mode=0o700)
        codex_home = self.workdir / "codex"
        codex_home.mkdir(mode=0o700)
        original_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
        auth = original_home / "auth.json"
        metadata = auth.lstat()
        if (not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode)
                or metadata.st_uid != os.getuid() or metadata.st_mode & 0o077):
            raise IsolationError("Isolation requires an owner-private regular Codex auth.json")
        auth = auth.resolve(strict=True)
        # No credential copy and no write-back. Login/token refresh is performed
        # outside the boundary; an expired login fails rather than widening access.
        (codex_home / "auth.json").symlink_to(auth)
        text = profile(executable, self.workdir, protected, auth, proxy_port)
        self.policy = protected / "process.sb"
        self.policy.write_text(text, encoding="utf-8")
        self.policy.chmod(0o400)
        self.environment = {
            "HOME": str(home), "CODEX_HOME": str(codex_home),
            "PATH": str(executable.parent), "TMPDIR": str(self.workdir),
            "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
            "HTTPS_PROXY": f"http://127.0.0.1:{proxy_port}",
            "HTTP_PROXY": f"http://127.0.0.1:{proxy_port}",
            "https_proxy": f"http://127.0.0.1:{proxy_port}",
            "http_proxy": f"http://127.0.0.1:{proxy_port}",
            "NO_PROXY": "", "no_proxy": "",
            "SSL_CERT_FILE": "/private/etc/ssl/cert.pem",
        }
        self.receipt = {
            "mode": "macos-seatbelt-v1", "policy_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "os_release": platform.release(),
            "system_ca_sha256": hashlib.sha256(SYSTEM_CA.read_bytes()).hexdigest(),
            "auth": "read_only_login", "egress": "openai_connect_allowlist_v1",
            "extra_processes": "denied_except_native_reexec",
        }

    def wrap(self, command):
        return [str(SANDBOX), "-f", str(self.policy), *command]


@contextmanager
def isolated(executable, workdir, deadline):
    if sys.platform != "darwin" or not SANDBOX.is_file():
        raise IsolationError("Codex process isolation requires macOS sandbox-exec")
    from .egress_proxy import EgressProxy, EgressProxyError
    try:
        with EgressProxy(deadline) as proxy:
            yield Boundary(executable, workdir, proxy.port)
    except (EgressProxyError, OSError, ValueError) as error:
        raise IsolationError("Codex egress boundary failed") from error
