import socket
import threading
import time
import unittest
from unittest import mock

from hyperreview.egress_proxy import (
    EgressProxy,
    _canonical_authority,
    _child_environment,
    _parse_connect_head,
    _relay,
    _resolve_public_addresses,
)


class EgressProxyPolicyTests(unittest.TestCase):
    def test_allowlist_is_exact_and_host_case_is_normalized(self):
        for host in ("chatgpt.com", "api.openai.com", "auth.openai.com"):
            self.assertEqual(_canonical_authority(host + ":443"), host)
            self.assertEqual(_canonical_authority(host.upper() + ":443"), host)
        for authority in (
            "chatgpt.com.", "evilchatgpt.com", "chatgpt.com:0443", "chatgpt.com:80",
            "user@chatgpt.com:443", "127.0.0.1:443", "[::1]:443", "chatgpt.com/path:443",
            "chatgpt.com:443/path", "chatgpt.com:443?x=1", "chatgpt.com:443,api.openai.com:443",
        ):
            with self.subTest(authority=authority), self.assertRaises(ValueError):
                _canonical_authority(authority)

    def test_connect_requires_one_matching_host_and_rejects_credential_or_body_headers(self):
        valid = (b"CONNECT api.openai.com:443 HTTP/1.1\r\n"
                 b"Host: api.openai.com:443\r\n\r\nTLS")
        self.assertEqual(_parse_connect_head(valid), ("api.openai.com", b"TLS"))
        invalid = (
            b"GET api.openai.com:443 HTTP/1.1\r\nHost: api.openai.com:443\r\n\r\n",
            b"CONNECT api.openai.com:443 HTTP/1.1\r\n\r\n",
            b"CONNECT api.openai.com:443 HTTP/1.1\r\nHost: evil.example\r\n\r\n",
            b"CONNECT api.openai.com:443 HTTP/1.1\r\nHost: api.openai.com:443\r\n"
            b"Host: api.openai.com:443\r\n\r\n",
            b"CONNECT api.openai.com:443 HTTP/1.1\r\nHost: api.openai.com:443\r\n"
            b"Proxy-Authorization: Basic abc\r\n\r\n",
            b"CONNECT api.openai.com:443 HTTP/1.1\r\nHost: api.openai.com:443\r\n"
            b"Content-Length: 0\r\n\r\n",
            b"CONNECT api.openai.com:443 HTTP/1.1\nHost: api.openai.com:443\n\n",
        )
        for request in invalid:
            with self.subTest(request=request), self.assertRaises(ValueError):
                _parse_connect_head(request)

    def test_header_size_and_field_count_are_bounded(self):
        with self.assertRaisesRegex(ValueError, "oversized"):
            _parse_connect_head(b"CONNECT api.openai.com:443 HTTP/1.1\r\n" +
                                b"X: " + b"x" * 9000 + b"\r\n\r\n")
        headers = b"".join(b"X%d: y\r\n" % index for index in range(33))
        with self.assertRaisesRegex(ValueError, "headers"):
            _parse_connect_head(b"CONNECT api.openai.com:443 HTTP/1.1\r\n" +
                                b"Host: api.openai.com:443\r\n" + headers + b"\r\n")

    def test_dns_rejects_entire_answer_if_any_result_is_not_global(self):
        good = (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "",
                ("8.8.8.8", 443))
        local = (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "",
                 ("127.0.0.1", 443))
        mapped_local = (socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP, "",
                        ("::ffff:127.0.0.1", 443, 0, 0))
        with mock.patch("hyperreview.egress_proxy.socket.getaddrinfo", return_value=[good]):
            self.assertEqual(_resolve_public_addresses("api.openai.com"),
                             [(socket.AF_INET, ("8.8.8.8", 443))])
        with mock.patch("hyperreview.egress_proxy.socket.getaddrinfo", return_value=[good, local]):
            with self.assertRaisesRegex(ValueError, "non-global"):
                _resolve_public_addresses("api.openai.com")
        with mock.patch("hyperreview.egress_proxy.socket.getaddrinfo", return_value=[mapped_local]):
            with self.assertRaisesRegex(ValueError, "non-global"):
                _resolve_public_addresses("api.openai.com")
        for address in ("224.0.0.1", "239.255.255.250", "240.0.0.1"):
            record = (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, 443))
            with self.subTest(address=address), \
                    mock.patch("hyperreview.egress_proxy.socket.getaddrinfo", return_value=[record]), \
                    self.assertRaisesRegex(ValueError, "non-global"):
                _resolve_public_addresses("api.openai.com")
        with mock.patch("hyperreview.egress_proxy.socket.getaddrinfo") as resolve:
            with self.assertRaises(ValueError):
                _resolve_public_addresses("127.0.0.1")
            resolve.assert_not_called()

    def test_deadline_must_be_a_future_monotonic_timestamp(self):
        with self.assertRaises(TimeoutError):
            EgressProxy(time.monotonic() - 1)
        for deadline in ("later", float("nan"), float("inf"), True):
            with self.subTest(deadline=deadline), self.assertRaises(ValueError):
                EgressProxy(deadline)


class EgressProxyLifecycleTests(unittest.TestCase):
    def test_relay_round_trips_with_socketpair_and_handles_write_only_readiness(self):
        client, relay_client = socket.socketpair()
        relay_upstream, remote = socket.socketpair()
        client.settimeout(1)
        remote.settimeout(1)
        relay = threading.Thread(target=_relay, args=(
            relay_client, relay_upstream, b"", time.monotonic() + 3), daemon=True)
        relay.start()
        try:
            client.sendall(b"ping")
            self.assertEqual(remote.recv(4), b"ping")
            remote.sendall(b"pong")
            self.assertEqual(client.recv(4), b"pong")
            client.shutdown(socket.SHUT_WR)
            remote.shutdown(socket.SHUT_WR)
            self.assertEqual(client.recv(1), b"")
            relay.join(timeout=1)
            self.assertFalse(relay.is_alive())
        finally:
            client.close()
            relay_client.close()
            relay_upstream.close()
            remote.close()
            relay.join(timeout=1)

    def test_child_starts_on_loopback_rejects_ip_authority_and_is_reaped(self):
        proxy = EgressProxy(time.monotonic() + 5)
        with proxy as running:
            self.assertTrue(1 <= running.port <= 65535)
            process = running._process
            self.assertIsNotNone(process)
            with socket.create_connection(("127.0.0.1", running.port), timeout=1) as client:
                client.sendall(b"CONNECT 127.0.0.1:443 HTTP/1.1\r\n"
                               b"Host: 127.0.0.1:443\r\n\r\n")
                response = client.recv(1024)
            self.assertTrue(response.startswith(b"HTTP/1.1 403"), response)
        self.assertIsNone(proxy.port)
        self.assertIsNone(proxy._process)
        self.assertIsNotNone(process.poll())

    def test_child_is_credential_free_by_construction(self):
        environment = _child_environment()
        self.assertEqual(set(environment), {"PATH", "LANG", "LC_ALL"})
        for key in ("OPENAI_API_KEY", "OPENAI_ORG_ID", "CODEX_HOME", "HTTPS_PROXY"):
            self.assertNotIn(key, environment)


if __name__ == "__main__":
    unittest.main()
