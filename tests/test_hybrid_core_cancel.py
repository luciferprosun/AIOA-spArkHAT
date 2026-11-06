"""Cancellation reaches the existing broker only after real Core admission."""

import inspect
import unittest
from pathlib import Path
from unittest.mock import patch

import test_sandbox_core as support

from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.mission.sandbox_linux import LinuxSandboxBroker, TrustedSandboxConfig
from runtime.providers.exact import CancellationToken


class CoreSandboxCancellationTests(unittest.TestCase):
    def fixture(self):
        fixture = support.SandboxCoreTests(
            "test_live_ack_builds_exact_stored_request_and_keeps_unknown_until_readback"
        )
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.assertIn(
            "cancel",
            inspect.signature(fixture.route.dispatch).parameters,
            "Core sandbox route does not forward the owner cancellation token",
        )
        return fixture

    def test_pre_cancelled_request_does_not_consume_or_dispatch(self):
        fixture = self.fixture()
        token = CancellationToken()
        token.cancel()
        before = fixture.base.path.read_bytes()
        with self.assertRaises(ValueError):
            fixture.route.dispatch(
                fixture.fx.p(),
                session_id=fixture.grant.session_id,
                warrant=fixture.warrant,
                operation=fixture.operation,
                reservation=fixture.reservation,
                completion=fixture.binding,
                cancel=token,
            )
        self.assertEqual(before, fixture.base.path.read_bytes())
        self.assertEqual(fixture.requests, [])

    def test_admitted_cancel_token_is_forwarded_to_same_linux_broker(self):
        fixture = self.fixture()
        token = CancellationToken()
        config = TrustedSandboxConfig(
            Path(fixture.base.tmp.name),
            b"{}",
            canonical_sha256({}),
            fixture.registry,
            b"{}",
            b"{}",
        )
        broker = LinuxSandboxBroker(config)
        fixture.route.executor = broker
        accepted = []

        def external_kernel_boundary(request, release_check, *, cancel=None):
            release_check()
            accepted.append((request, cancel))
            token.cancel()

        with patch.object(broker, "dispatch", side_effect=external_kernel_boundary):
            result = fixture.route.dispatch(
                fixture.fx.p(),
                session_id=fixture.grant.session_id,
                warrant=fixture.warrant,
                operation=fixture.operation,
                reservation=fixture.reservation,
                completion=fixture.binding,
                cancel=token,
            )
        self.assertEqual(result["outcome"]["contract_type"], "Unknown")
        self.assertEqual(len(accepted), 1)
        self.assertIs(accepted[0][1], token)
        self.assertEqual(accepted[0][0].warrant_digest, fixture.warrant.digest())


if __name__ == "__main__":
    unittest.main()
