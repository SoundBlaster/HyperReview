"""Small, killable HTTP CONNECT egress proxy for the native Codex CLI.

The parent launches this file with ``python -I``.  The child uses only the
standard library, accepts CONNECT for three exact HTTPS hosts, resolves them
itself, and connects only to globally routable addresses.  It never logs
request data or inspects TLS.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
import ipaddress
import math
import os
from pathlib import Path
import re
import selectors
import signal
import socket
import socketserver
import subprocess
import sys
import threading
import time


_ALLOWED_HOSTS = frozenset(("chatgpt.com", "api.openai.com", "auth.openai.com"))
_MAX_HEADER_BYTES = 8 * 1024
_MAX_HEADER_FIELDS = 32
_MAX_CONNECTIONS = 8
_MAX_TUNNEL_BYTES = 64 * 1024 * 1024
_MAX_TUNNEL_BUFFER_BYTES = 256 * 1024
_HEADER_TIMEOUT = 5.0
_CONNECT_TIMEOUT = 5.0
_STOP_GRACE_SECONDS = 1.0
_KILL_GRACE_SECONDS = 1.0
_AUTHORITY_RE = re.compile(r"([A-Za-z0-9.-]+):443\Z", re.ASCII)


class EgressProxyError(RuntimeError):
    """Raised when the isolated egress proxy cannot start or stop cleanly."""


def _canonical_authority(authority: str) -> str:
    """Return the lower-case host for a canonical allowlisted ``host:443``."""
    if type(authority) is not str or not authority or len(authority) > 255:
        raise ValueError("invalid CONNECT authority")
    match = _AUTHORITY_RE.fullmatch(authority)
    if match is None:
        raise ValueError("invalid CONNECT authority")
    # DNS names are case-insensitive.  Normalize ASCII case, but reject other
    # spellings (trailing dot, IDN, IP literal, alternate port representation).
    host = match.group(1).lower()
    if host not in _ALLOWED_HOSTS:
        raise ValueError("CONNECT authority is not allowed")
    return host


def _parse_connect_head(data: bytes) -> tuple[str, bytes]:
    """Parse bounded request headers and return (host, already-read tunnel bytes)."""
    end = data.find(b"\r\n\r\n")
    if end < 0 or end + 4 > _MAX_HEADER_BYTES:
        raise ValueError("incomplete or oversized CONNECT headers")
    head, remainder = data[:end], data[end + 4:]
    try:
        lines = head.decode("ascii").split("\r\n")
    except UnicodeDecodeError as error:
        raise ValueError("non-ASCII CONNECT headers") from error
    if not lines or len(lines) - 1 > _MAX_HEADER_FIELDS:
        raise ValueError("invalid CONNECT headers")
    parts = lines[0].split(" ")
    if len(parts) != 3 or parts[0] != "CONNECT" or parts[2] not in ("HTTP/1.0", "HTTP/1.1"):
        raise ValueError("only HTTP CONNECT is allowed")
    host = _canonical_authority(parts[1])
    host_headers = 0
    for line in lines[1:]:
        if not line or line[0] in " \t" or ":" not in line:
            raise ValueError("invalid CONNECT header field")
        name, value = line.split(":", 1)
        if not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name, re.ASCII):
            raise ValueError("invalid CONNECT header name")
        if any(ord(char) < 32 and char != "\t" or ord(char) == 127 for char in value):
            raise ValueError("invalid CONNECT header value")
        lowered = name.lower()
        if lowered == "host":
            host_headers += 1
            if value.strip().lower() != parts[1].lower():
                raise ValueError("Host header does not match CONNECT authority")
        if lowered in ("content-length", "transfer-encoding", "authorization", "proxy-authorization"):
            raise ValueError("unsupported CONNECT header")
    if host_headers != 1:
        raise ValueError("CONNECT requires one matching Host header")
    return host, remainder


def _resolve_public_addresses(host: str) -> list[tuple[int, tuple]]:
    """Resolve a validated host and reject the whole answer if any IP is non-global."""
    if host not in _ALLOWED_HOSTS:
        raise ValueError("host is not allowed")
    records = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
    addresses: list[tuple[int, tuple]] = []
    seen = set()
    if not records:
        raise OSError("host did not resolve")
    for family, socktype, proto, _canonname, sockaddr in records:
        if (family not in (socket.AF_INET, socket.AF_INET6)
                or socktype != socket.SOCK_STREAM or proto != socket.IPPROTO_TCP):
            raise ValueError("host returned an unsupported address")
        raw_address = sockaddr[0]
        if "%" in raw_address or family == socket.AF_INET6 and sockaddr[3] != 0:
            raise ValueError("host returned a scoped address")
        address = ipaddress.ip_address(raw_address)
        mapped = getattr(address, "ipv4_mapped", None)
        if (not address.is_global
                or mapped is not None and not mapped.is_global):
            raise ValueError("host resolved to a non-global address")
        if (family, sockaddr) not in seen:
            seen.add((family, sockaddr))
            addresses.append((family, sockaddr))
    if not addresses:
        raise OSError("host did not resolve to a usable address")
    return addresses


def _connect_validated(host: str, deadline: float) -> socket.socket:
    """Connect directly to one validated IP, with no second hostname lookup."""
    last_error: OSError | None = None
    for family, sockaddr in _resolve_public_addresses(host):
        timeout = min(_CONNECT_TIMEOUT, deadline - time.monotonic())
        if timeout <= 0:
            raise TimeoutError("proxy deadline elapsed")
        upstream = socket.socket(family, socket.SOCK_STREAM)
        upstream.settimeout(timeout)
        try:
            upstream.connect(sockaddr)
            upstream.setblocking(False)
            return upstream
        except OSError as error:
            last_error = error
            upstream.close()
    if last_error is not None:
        raise last_error
    raise OSError("no usable address")


def _relay(client: socket.socket, upstream: socket.socket, initial: bytes, deadline: float) -> None:
    """Relay an opaque TLS byte stream with a total byte and lifetime cap."""
    selector = selectors.DefaultSelector()
    peers = {client: upstream, upstream: client}
    buffers = {client: bytearray(), upstream: bytearray()}
    if initial:
        buffers[upstream].extend(initial)
    total = 0
    eof = set()
    try:
        for stream in peers:
            stream.setblocking(False)
            selector.register(stream, selectors.EVENT_READ | (selectors.EVENT_WRITE
                               if buffers[stream] else 0))
        total = len(initial)
        while selector.get_map() and time.monotonic() < deadline and total < _MAX_TUNNEL_BYTES:
            events = selector.select(min(1.0, max(0.0, deadline - time.monotonic())))
            for key, ready_mask in events:
                source = key.fileobj
                if ready_mask & selectors.EVENT_READ:
                    capacity = min(_MAX_TUNNEL_BUFFER_BYTES - len(buffers[peers[source]]),
                                   _MAX_TUNNEL_BYTES - total, 65536)
                    if capacity > 0:
                        try:
                            chunk = source.recv(capacity)
                        except OSError:
                            return
                        if not chunk:
                            eof.add(source)
                        else:
                            total += len(chunk)
                            buffers[peers[source]].extend(chunk)
                if ready_mask & selectors.EVENT_WRITE and buffers[source]:
                    try:
                        sent = source.send(buffers[source])
                    except OSError:
                        return
                    if sent == 0:
                        return
                    del buffers[source][:sent]
                for stream in peers:
                    if stream in eof and not buffers[peers[stream]]:
                        try:
                            peers[stream].shutdown(socket.SHUT_WR)
                        except OSError:
                            pass
                    if stream in eof and not buffers[stream]:
                        try:
                            selector.unregister(stream)
                        except KeyError:
                            pass
                        continue
                    events_mask = (0 if stream in eof or total >= _MAX_TUNNEL_BYTES
                                   or len(buffers[peers[stream]]) >= _MAX_TUNNEL_BUFFER_BYTES
                                   else selectors.EVENT_READ)
                    if buffers[stream]:
                        events_mask |= selectors.EVENT_WRITE
                    if events_mask:
                        try:
                            selector.modify(stream, events_mask)
                        except KeyError:
                            selector.register(stream, events_mask)
                    else:
                        try:
                            selector.unregister(stream)
                        except KeyError:
                            pass
    finally:
        selector.close()


class _BoundedThreadingServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = False
    daemon_threads = True
    block_on_close = False

    def __init__(self, address, handler, deadline):
        self.deadline = deadline
        self._slots = threading.BoundedSemaphore(_MAX_CONNECTIONS)
        super().__init__(address, handler)

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            request.close()
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


class _ConnectHandler(socketserver.BaseRequestHandler):
    def handle(self):
        server = self.server
        deadline = server.deadline
        client = self.request
        try:
            data = bytearray()
            client.settimeout(min(_HEADER_TIMEOUT, max(0.01, deadline - time.monotonic())))
            while b"\r\n\r\n" not in data:
                if time.monotonic() >= deadline or len(data) >= _MAX_HEADER_BYTES:
                    raise ValueError("CONNECT headers exceeded bounds")
                chunk = client.recv(min(4096, _MAX_HEADER_BYTES + 1 - len(data)))
                if not chunk:
                    return
                data.extend(chunk)
            host, initial = _parse_connect_head(bytes(data))
            upstream = _connect_validated(host, deadline)
        except (OSError, ValueError, TimeoutError):
            try:
                client.sendall(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\nContent-Length: 0\r\n\r\n")
            except OSError:
                pass
            return
        try:
            client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            _relay(client, upstream, initial, deadline)
        except OSError:
            pass
        finally:
            upstream.close()


def _child_main(deadline: float) -> int:
    if not math.isfinite(deadline) or deadline <= time.monotonic():
        return 2
    server = None
    try:
        server = _BoundedThreadingServer(("127.0.0.1", 0), _ConnectHandler, deadline)
        # One machine-readable startup record; no request or destination data is logged.
        sys.stdout.write(f"{server.server_address[1]}\n")
        sys.stdout.flush()
        while time.monotonic() < deadline:
            server.timeout = min(0.25, max(0.01, deadline - time.monotonic()))
            server.handle_request()
    except (OSError, ValueError):
        return 1
    finally:
        if server is not None:
            server.server_close()
    return 0


def _child_environment() -> dict[str, str]:
    """Return a deliberately credential-free environment for the isolated child."""
    return {"PATH": os.defpath, "LANG": "C", "LC_ALL": "C"}


class EgressProxy(AbstractContextManager):
    """Manage an isolated loopback CONNECT proxy until an absolute monotonic deadline.

    Usage::

        with EgressProxy(deadline=time.monotonic() + timeout) as proxy:
            launch_codex(proxy_port=proxy.port)

    The child has a credential-free environment and is forcibly reaped on exit.
    """

    def __init__(self, deadline: float):
        if type(deadline) not in (int, float) or not math.isfinite(deadline):
            raise ValueError("deadline must be an absolute monotonic timestamp")
        if deadline <= time.monotonic():
            raise TimeoutError("proxy deadline has elapsed")
        self.deadline = float(deadline)
        self.port: int | None = None
        self._process: subprocess.Popen | None = None

    def __enter__(self) -> "EgressProxy":
        if self._process is not None:
            raise RuntimeError("proxy is already started")
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("proxy deadline has elapsed")
        script = str(Path(__file__).resolve())
        try:
            self._process = subprocess.Popen(
                [sys.executable, "-I", script, "--child", repr(self.deadline)],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                cwd="/", env=_child_environment(), close_fds=True, start_new_session=True,
            )
        except OSError as error:
            raise EgressProxyError("proxy child could not be started") from error
        try:
            assert self._process.stdout is not None
            selector = selectors.DefaultSelector()
            startup = bytearray()
            try:
                descriptor = self._process.stdout.fileno()
                os.set_blocking(descriptor, False)
                selector.register(descriptor, selectors.EVENT_READ)
                while time.monotonic() < self.deadline:
                    if self._process.poll() is not None:
                        raise EgressProxyError("proxy child failed during startup")
                    ready = selector.select(min(0.1, self.deadline - time.monotonic()))
                    if ready:
                        try:
                            chunk = os.read(descriptor, 32 - len(startup))
                        except BlockingIOError:
                            continue
                        if not chunk:
                            raise EgressProxyError("proxy child closed startup output")
                        startup.extend(chunk)
                        if len(startup) > 31:
                            raise EgressProxyError("proxy child startup record exceeded its bound")
                        newline = startup.find(b"\n")
                        if newline < 0:
                            continue
                        if newline != len(startup) - 1 or not startup[:-1].isdigit():
                            raise EgressProxyError("proxy child returned an invalid startup record")
                        port = int(startup[:-1])
                        if not 1 <= port <= 65535:
                            raise EgressProxyError("proxy child returned an invalid port")
                        self.port = port
                        return self
            finally:
                selector.close()
            raise TimeoutError("proxy startup exceeded its deadline")
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        process = self._process
        if process is None:
            return
        self.port = None
        if process.poll() is not None:
            process.wait()
            if process.stdout is not None:
                process.stdout.close()
            self._process = None
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=_STOP_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=_KILL_GRACE_SECONDS)
            except subprocess.TimeoutExpired as error:
                raise EgressProxyError("proxy child could not be reaped after SIGKILL") from error
        if process.stdout is not None:
            process.stdout.close()
        self._process = None

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "--child":
        raise SystemExit(2)
    try:
        raise SystemExit(_child_main(float(sys.argv[2])))
    except (ValueError, OverflowError):
        raise SystemExit(2)
