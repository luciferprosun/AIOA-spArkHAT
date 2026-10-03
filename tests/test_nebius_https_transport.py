from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import threading
import time
import unittest
from unittest.mock import patch

from runtime.service_guard.contracts import GuardError
from runtime.service_guard.https_transport import (
    NebiusHttpsEffectTransport,
    validate_serverless_endpoint,
)
from runtime.service_guard.target import TargetUnknown


class _FixtureHandler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802 - standard library handler API
        self.server.calls += 1
        length = int(self.headers.get("Content-Length", "0"))
        self.server.request_body = self.rfile.read(length)
        self.server.request_headers = dict(self.headers)
        if self.server.delay:
            time.sleep(self.server.delay)
        body = self.server.response_body
        self.send_response(self.server.response_status)
        self.send_header("Content-Type", self.server.response_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            pass

    def log_message(self, *_args):
        return


@contextmanager
def fixture_server(*, response=None, status=200, content_type="application/json", delay=0):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FixtureHandler)
    server.calls = 0
    server.request_body = b""
    server.request_headers = {}
    server.response_body = json.dumps(response or {"ok": True}).encode()
    server.response_status = status
    server.response_type = content_type
    server.delay = delay
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class NebiusHttpsEffectTransportTests(unittest.TestCase):
    def test_live_endpoint_validation_rejects_ambiguous_or_private_destinations(self):
        invalid = (
            "http://serverless.nebius.example/invoke",
            "https://user@serverless.nebius.example/invoke",
            "https://serverless.nebius.example/invoke?token=x",
            "https://serverless.nebius.example/invoke#fragment",
            "https://127.0.0.1/invoke",
            "https://localhost/invoke",
            "https://10.2.3.4/invoke",
            "https://serverless.nebius.example:8443/invoke",
        )
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(GuardError):
                validate_serverless_endpoint(value)

        self.assertEqual(
            "https://serverless.nebius.example/invoke",
            validate_serverless_endpoint("https://serverless.nebius.example/invoke"),
        )

    def test_test_scope_accepts_only_explicit_loopback_http(self):
        self.assertEqual(
            "http://127.0.0.1:43119/invoke",
            validate_serverless_endpoint(
                "http://127.0.0.1:43119/invoke", transport_scope="TEST"
            ),
        )
        for value in (
            "http://localhost:43119/invoke",
            "http://0.0.0.0:43119/invoke",
            "https://serverless.nebius.example/invoke",
        ):
            with self.subTest(value=value), self.assertRaises(GuardError):
                validate_serverless_endpoint(value, transport_scope="TEST")

    def test_loopback_fixture_receives_one_typed_json_request_and_bearer_auth(self):
        response = {"target_id": "target-a", "mode": "NORMAL", "revision": 1,
                    "effect_count": 0}
        with fixture_server(response=response) as server:
            endpoint = f"http://127.0.0.1:{server.server_port}/invoke"
            transport = NebiusHttpsEffectTransport(
                endpoint_url=endpoint,
                auth_token="fixture-auth-not-real",
                timeout_seconds=2,
                transport_scope="TEST",
            )
            request = {"schema": "aioa.nebius-serverless-target.v1",
                       "action": "READ_STATE", "target_id": "target-a",
                       "scope": ["tenant", "owner", "space", "slot"]}

            result = transport.invoke(request)

        self.assertEqual(response, result)
        self.assertEqual(1, server.calls)
        self.assertEqual(request, json.loads(server.request_body))
        self.assertEqual("application/json", server.request_headers["Content-Type"])
        self.assertEqual("Bearer fixture-auth-not-real",
                         server.request_headers["Authorization"])

    def test_arbitrary_action_is_rejected_before_transport(self):
        with fixture_server() as server:
            transport = NebiusHttpsEffectTransport(
                endpoint_url=f"http://127.0.0.1:{server.server_port}/invoke",
                auth_token="fixture-auth-not-real",
                timeout_seconds=2,
                transport_scope="TEST",
            )
            with self.assertRaises(GuardError) as caught:
                transport.invoke({"schema": "aioa.nebius-serverless-target.v1",
                                  "action": "RUN_SHELL"})
        self.assertEqual("TARGET_OPERATION_DENIED", caught.exception.code)
        self.assertEqual(0, server.calls)

    def test_response_limit_fails_closed(self):
        with fixture_server(response={"padding": "x" * 2000}) as server:
            transport = NebiusHttpsEffectTransport(
                endpoint_url=f"http://127.0.0.1:{server.server_port}/invoke",
                auth_token="fixture-auth-not-real",
                timeout_seconds=2,
                max_response_bytes=512,
                transport_scope="TEST",
            )
            with self.assertRaises(TargetUnknown):
                transport.invoke({"schema": "aioa.nebius-serverless-target.v1",
                                  "action": "READ_STATE"})
        self.assertEqual(1, server.calls)

    def test_timeout_is_unknown_and_never_retried(self):
        with fixture_server(delay=0.2) as server:
            transport = NebiusHttpsEffectTransport(
                endpoint_url=f"http://127.0.0.1:{server.server_port}/invoke",
                auth_token="fixture-auth-not-real",
                timeout_seconds=0.05,
                transport_scope="TEST",
            )
            with self.assertRaises(TargetUnknown):
                transport.invoke({"schema": "aioa.nebius-serverless-target.v1",
                                  "action": "READ_RECEIPT",
                                  "idempotency_key": "a" * 64})
        self.assertEqual(1, server.calls)

    def test_environment_composition_requires_both_live_values(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(GuardError):
            NebiusHttpsEffectTransport.from_environment()
        values = {
            "NEBIUS_SERVERLESS_ENDPOINT_URL": "https://serverless.nebius.example/invoke",
            "NEBIUS_SERVERLESS_AUTH_TOKEN": "cloud-injected-secret",
        }
        with patch.dict(os.environ, values, clear=True):
            transport = NebiusHttpsEffectTransport.from_environment()
        self.assertEqual("LIVE", transport.transport_scope)
        self.assertNotIn("cloud-injected-secret", repr(transport))


if __name__ == "__main__":
    unittest.main()
