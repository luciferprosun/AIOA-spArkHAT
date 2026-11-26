"""Disposable authority/HTTPS fixtures for the exact B operator entry; zero paid calls."""

import hashlib
import json
import os
import time
import unittest
from unittest.mock import patch

import nz13_native_foundation_support as fx
from runtime.core_admission import AdmissionError, Capability
from runtime.meta_hackathon import model_qualification as lane
from runtime.meta_hackathon.native_authority import NativePhase
from runtime.mobile_gateway import wire
from runtime.providers.exact import ProviderResult, exact_request_body
from runtime.providers.live_gate import RepositorySourceStateReader


class NativeModelQualificationTests(unittest.TestCase):
    def create(self, *, enabled=True):
        original = fx.config_data

        def config(root):
            body = original(root)
            if enabled:
                body["profile"] = "OWNED_WORKER_MODEL_B_V1"
            return body

        with patch.object(fx, "config_data", side_effect=config):
            host, _ = fx.new_host(self)
        fx.fixture_tls(host)
        fx.initialize(host)
        host.foundation.lifecycle._phase = NativePhase.ACTIVE
        self.enterContext(patch.object(host, "_existing_profile", object()))
        self.enterContext(patch.dict(os.environ, {"NEBIUS_API_KEY": "fixture"}))
        self.enterContext(
            patch.object(
                RepositorySourceStateReader,
                "__call__",
                return_value=(host.source[0], "d" * 64, "e" * 64),
            )
        )
        directory = host.root / "worker-model"
        directory.mkdir(mode=0o700)
        evidence = b"Local test billing evidence"
        (directory / "account-review.bin").write_bytes(evidence)
        (directory / "account-review.bin").chmod(0o600)
        data = {
            "schema": "aioa.worker-account-review.v1",
            "provider": "nebius",
            "model": lane.MODEL,
            "currency": "USD",
            "source_url": lane.PRICE,
            "input_nano_per_token": 60,
            "output_nano_per_token": 240,
            "additional_fees": False,
            "available_nano_usd": 1000000,
            "reviewed_at": int(time.time()),
            "account_evidence_sha256": hashlib.sha256(evidence).hexdigest(),
        }
        self.billing = directory / "billing.json"
        self.billing.write_bytes(wire.canonical(data))
        self.billing.chmod(0o600)
        self.host = host
        self.posts = 0
        self.last_scope = None
        self.candidate_text = lane.CONTENT

    def op(self, name, **args):
        return self.host.operator_request(
            os.getuid(), {"op": "worker_model_" + name, **args}
        )

    def reply(self, connection, request, cancel, deadline, *, fixture, before_send):
        self.assertFalse(fixture)
        self.assertEqual("fixture", connection.api_key)
        before_send(exact_request_body(request))
        self.posts += 1
        self.last_scope = request.transport_scope
        prefix = "Return only a JSON candidate with these exact bindings and proposed files: "
        envelope = json.loads(request.messages[0].content.removeprefix(prefix))
        envelope["files"] = [{"path": lane.FILE, "text": self.candidate_text}]
        return ProviderResult(
            json.dumps(envelope),
            "nebius",
            lane.MODEL,
            lane.MODEL,
            "EXACT_MATCH",
            "fixture-provider-receipt",
            {"prompt_tokens": 100, "completion_tokens": 80, "total_tokens": 180},
            "stop",
            request.transport_scope,
        )

    def test_real_owner_socket_entry_signs_once_fixed_oracle_reconciles_and_reads_original(
        self,
    ):
        self.create()
        with patch(
            "runtime.mission.qualified_worker.generate_http_exact",
            side_effect=self.reply,
        ):
            review = self.op("prepare")
            self.assertEqual(0, self.posts)
            with self.assertRaises(ValueError):
                self.op("approve", review_digest="0" * 64)
            signed = self.op("approve", review_digest=review["review_digest"])
            wire.verify(self.host.identity.spki, signed["signature"], signed["proof"])
            self.assertEqual("NONE", signed["proof"]["candidate_authority"])
            self.assertEqual(100 * 60 + 80 * 240, signed["proof"]["estimated_nano_usd"])
            self.assertEqual(1, self.posts)
            self.assertEqual(signed, self.op("readback"))
            self.assertEqual(signed, self.op("readback"))
            with self.assertRaises((ValueError, AdmissionError)):
                self.op("prepare")
            state = self.host.foundation.governor.inspect(
                self.host.core.local_operator(Capability.READ)
            )
            self.assertEqual(
                "COMMITTED", state["reservations"]["paired-" + lane.TASK]["state"]
            )
            self.assertEqual(1, self.posts)

            from runtime.meta_hackathon import runtime_adapter

            spec = self.host.foundation.spec
            source = self.host.source
            self.assertTrue(self.host.close()["closed"])
            with patch.object(
                runtime_adapter,
                "_desktop_operator_uid",
                return_value=(os.getuid(), {"uid": os.getuid()}),
            ):
                other = runtime_adapter.NativeMobileComposition(
                    self.host.root,
                    origin=self.host.origin,
                    source_probe=lambda: source,
                    host_composition=spec,
                )
            self.addCleanup(other.close)
            fx.fixture_tls(other)
            with patch.object(other, "_existing_profile", object()):
                cold = other.operator_request(
                    os.getuid(), {"op": "worker_model_readback"}
                )
            self.assertEqual(signed, cold)
            self.assertEqual(1, self.posts)

    def test_changed_candidate_cannot_settle_from_successful_provider_reply(self):
        self.create()
        self.candidate_text = "different bytes"
        with patch(
            "runtime.mission.qualified_worker.generate_http_exact",
            side_effect=self.reply,
        ):
            review = self.op("prepare")
            with self.assertRaisesRegex(ValueError, "WORKER_ORACLE_DENIED"):
                self.op("approve", review_digest=review["review_digest"])
            self.assertEqual("UNKNOWN_HELD", self.op("readback")["state"])
            self.assertEqual(1, self.posts)

    def test_lost_response_retains_charge_and_zero_redispatch(self):
        self.create()

        def lost(*args, **kwargs):
            self.reply(*args, **kwargs)
            raise OSError("offline ACK loss")

        with patch(
            "runtime.mission.qualified_worker.generate_http_exact", side_effect=lost
        ):
            review = self.op("prepare")
            with self.assertRaises(ValueError):
                self.op("approve", review_digest=review["review_digest"])
            self.assertEqual("UNKNOWN_HELD", self.op("readback")["state"])
            with self.assertRaises((ValueError, AdmissionError)):
                self.op("prepare")
            self.assertEqual(1, self.posts)

    def test_offline_profile_and_unbound_billing_refuse(self):
        self.create(enabled=False)
        with self.assertRaises(AdmissionError):
            self.op("prepare")
        self.assertNotIn(
            lane.MODEL,
            self.host.core.local_operator(Capability.COMMIT).model_binding_ids,
        )

    def test_scope_rejects_extra_fields_and_cost_evidence_drift(self):
        self.create()
        with self.assertRaises(ValueError):
            self.op("prepare", instruction="another job")
        review = self.op("prepare")
        self.billing.write_bytes(b"{}")
        with self.assertRaises(ValueError):
            self.op("approve", review_digest=review["review_digest"])
        self.assertEqual("NOT_STARTED", self.op("readback")["state"])
