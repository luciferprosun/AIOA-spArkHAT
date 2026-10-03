from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from nv09_support import GuardFixture, SCOPE
from runtime.core_admission import Capability
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.service_guard.contracts import GuardError
from runtime.service_guard.serverless_worker import handle_target_request
from runtime.service_guard.target import CloudEffectTargetClient, TargetUnknown


class MemoryTargetStore:
    """Test-only durable-store contract implementation with atomic idempotency."""

    def __init__(self, scope, target_id):
        self.scope, self.target_id = scope, target_id
        self.lock = threading.RLock()
        self.state = {"target_id": target_id, "scope": list(scope.binding()),
                      "mode": "NORMAL", "revision": 1, "effect_count": 0}
        self.receipts = {}
        self.apply_count = 0

    def read_state(self, target_id, scope):
        if (target_id, scope) != (self.target_id, list(self.scope.binding())):
            raise ValueError("TARGET_BINDING_MISMATCH")
        with self.lock:
            return dict(self.state)

    def read_receipt(self, target_id, scope, idempotency_key):
        if (target_id, scope) != (self.target_id, list(self.scope.binding())):
            raise ValueError("TARGET_BINDING_MISMATCH")
        with self.lock:
            return self.receipts.get(idempotency_key)

    def apply_once(self, command):
        with self.lock:
            previous = self.receipts.get(command["idempotency_key"])
            if previous is not None:
                if previous["request_digest"] != command["request_digest"]:
                    raise ValueError("TARGET_IDEMPOTENCY_CONFLICT")
                return previous
            if (self.state["mode"] != "NORMAL"
                    or self.state["revision"] != command["expected_revision"]
                    or self.state["effect_count"] != command["before_effect_count"]):
                raise ValueError("STALE_TARGET")
            self.apply_count += 1
            self.state.update(mode="MAINTENANCE", revision=self.state["revision"] + 1,
                              effect_count=self.state["effect_count"] + 1)
            receipt = {**command, "receipt_id": "target-" + command["idempotency_key"],
                       "new_revision": self.state["revision"],
                       "effect_count": self.state["effect_count"],
                       "mode": self.state["mode"], "dispatched_at": command["expires_at"] - 1}
            self.receipts[command["idempotency_key"]] = receipt
            return receipt


class FakeNebiusJobTransport:
    def __init__(self, store, *, drop_apply_ack=False):
        self.store, self.drop_apply_ack = store, drop_apply_ack
        self.calls = []

    def invoke(self, request):
        self.calls.append(request["action"])
        response = handle_target_request(request, self.store)
        if request["action"] == "APPLY_SET_MAINTENANCE" and self.drop_apply_ack:
            self.drop_apply_ack = False
            raise TimeoutError("fixture lost acknowledgement")
        return response


class ServerlessEffectTransportTests(unittest.TestCase):
    def make_fixture(self, root, *, drop_apply_ack=False):
        target_id = "nebius-disposable-target"
        store = MemoryTargetStore(SCOPE, target_id)
        transport = FakeNebiusJobTransport(store, drop_apply_ack=drop_apply_ack)
        client = CloudEffectTargetClient(scope=SCOPE, target_id=target_id,
                                         transport=transport)
        fixture = GuardFixture(root, client)
        return fixture, store, transport

    def test_service_guard_uses_typed_cloud_transport_and_verifies_independent_readback(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture, store, transport = self.make_fixture(Path(directory))
            try:
                fixture.approve()
                result = fixture.tick()
                self.assertEqual("VERIFIED", result["status"], result)
                self.assertEqual(1, store.apply_count)
                self.assertIn("READ_STATE", transport.calls)
                self.assertIn("READ_RECEIPT", transport.calls)
                self.assertEqual(1, transport.calls.count("APPLY_SET_MAINTENANCE"))
                applied_at = transport.calls.index("APPLY_SET_MAINTENANCE")
                self.assertTrue(all(action == "READ_STATE" for action in transport.calls[:applied_at]))
                self.assertEqual("READ_RECEIPT", transport.calls[applied_at + 1])
                self.assertEqual("READ_STATE", transport.calls[-1])
            finally:
                fixture.close()

    def test_timeout_reconciles_receipt_without_replaying_cloud_effect(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture, store, transport = self.make_fixture(Path(directory), drop_apply_ack=True)
            try:
                fixture.approve()
                first = fixture.tick()
                self.assertEqual("UNKNOWN", first["status"], first)
                second = fixture.tick()
                self.assertEqual("VERIFIED", second["status"], second)
                self.assertEqual(1, store.apply_count)
                self.assertEqual(1, transport.calls.count("APPLY_SET_MAINTENANCE"))
            finally:
                fixture.close()

    def test_serverless_worker_accepts_only_narrow_typed_actions(self):
        store = MemoryTargetStore(SCOPE, "nebius-disposable-target")
        request = {"schema": "aioa.nebius-serverless-target.v1", "action": "RUN_SHELL",
                   "target_id": store.target_id, "scope": list(SCOPE.binding())}
        with self.assertRaises(GuardError) as caught:
            handle_target_request(request, store)
        self.assertEqual("TARGET_OPERATION_DENIED", caught.exception.code)
        self.assertEqual(0, store.apply_count)

    def test_cloud_effect_cannot_dispatch_without_existing_serviceguard_authorization(self):
        store = MemoryTargetStore(SCOPE, "nebius-disposable-target")
        transport = FakeNebiusJobTransport(store)
        client = CloudEffectTargetClient(scope=SCOPE, target_id=store.target_id,
                                         transport=transport)
        with self.assertRaises(GuardError) as caught:
            client.dispatch({}, authorization=None)
        self.assertEqual("EFFECT_AUTHORIZATION_DENIED", caught.exception.code)
        self.assertEqual([], transport.calls)
        self.assertEqual(0, store.apply_count)

    def test_worker_apply_is_idempotent_for_the_same_receipt_key(self):
        store = MemoryTargetStore(SCOPE, "nebius-disposable-target")
        command = {
            "operation_id": "cloud-operation", "scope": list(SCOPE.binding()),
            "target_id": store.target_id, "expected_revision": 1,
            "before_effect_count": 0, "effect_class": "SET_MAINTENANCE",
            "approval_digest": "a" * 64, "policy_digest": "b" * 64,
            "proposal_digest": "c" * 64, "expires_at": 2**53,
            "idempotency_key": "d" * 64,
        }
        command["request_digest"] = canonical_sha256(command)
        request = {"schema": "aioa.nebius-serverless-target.v1",
                   "action": "APPLY_SET_MAINTENANCE", "target_id": store.target_id,
                   "scope": list(SCOPE.binding()), "command": command}
        first = handle_target_request(request, store)
        second = handle_target_request(request, store)
        self.assertEqual(first, second)
        self.assertEqual(1, store.apply_count)


if __name__ == "__main__":
    unittest.main()
