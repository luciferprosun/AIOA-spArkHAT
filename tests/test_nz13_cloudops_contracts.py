"""W7A deltas through the existing Core, with synthetic secret fixtures only."""

import hashlib
import json
import unittest
from unittest.mock import patch
from uuid import UUID

import test_nonzero_core_authority as authority_fixture

if authority_fixture.AVAILABLE:
    from nonzero_cloudops.models import (
        AuditEvent,
        LocalExecutionIntent,
        ResourceQuery,
        contains_sensitive_material,
        redact_sensitive_text,
    )
    from nonzero_cloudops.models.digest import compute_evidence_digest
    from nonzero_cloudops.provenance import public_evidence
from nonzero_legacy_fixture import historical_intent_format


def synthetic_credential(prefix):
    return prefix + "_" + "A" * 40


@unittest.skipUnless(authority_fixture.AVAILABLE, "NonZero optional extra is not installed")
class RedactionContractTests(unittest.TestCase):
    def test_all_github_token_families_are_detected_and_fully_removed(self):
        for prefix in ("ghp", "gho", "ghu", "ghs", "ghr", "github_pat"):
            with self.subTest(family=prefix):
                value = synthetic_credential(prefix)
                self.assertTrue(contains_sensitive_material(value), "Missed token family")
                self.assertTrue(
                    redact_sensitive_text("(" + value + ").") == "([REDACTED]).",
                    "Credential body survived redaction",
                )

    def test_stateless_installation_token_removes_all_jwt_segments(self):
        # Synthetic shape only; no usable signature or real GitHub credential.
        value = "ghs_123456_" + "A" * 44 + "." + "B-" * 32 + "." + "C_" * 43
        self.assertTrue(contains_sensitive_material(value))
        self.assertTrue(
            redact_sensitive_text("(" + value + ");") == "([REDACTED]);",
            "Stateless credential segments survived redaction",
        )

    def test_unicode_adjacency_and_nested_json_cannot_hide_tokens(self):
        for prefix in ("ghp", "gho", "ghu", "ghs", "ghr", "github_pat"):
            value = "ż" + synthetic_credential(prefix) + "界"
            with self.subTest(family=prefix):
                self.assertTrue(contains_sensitive_material(value), "Unicode boundary bypass")
                self.assertTrue(
                    contains_sensitive_material({"items": [{"message": value}]}),
                    "Nested JSON boundary bypass",
                )
                self.assertTrue(
                    redact_sensitive_text(value) == "ż[REDACTED]界",
                    "Unicode-adjacent credential survived",
                )

    def test_short_examples_and_unrelated_identifiers_remain_readable(self):
        for value in ("ghp_short", "ghx_" + "A" * 40, "github_pat", "ghr_1234567", "graph_hash"):
            with self.subTest(example=value):
                self.assertFalse(contains_sensitive_material(value))
                self.assertEqual(redact_sensitive_text(value), value)

    def test_public_projection_redacts_nested_strings_and_private_fields(self):
        value = synthetic_credential("ghu")
        result = public_evidence({"message": ["received " + value], "token": value})
        self.assertTrue(
            result == {"message": ["received [REDACTED]"]},
            "Public projection retained credential material",
        )

    def test_public_projection_drops_secret_keys_and_case_aliases(self):
        value = synthetic_credential("ghu")
        result = public_evidence({"items": [{value: "label", "Authorization": "opaque"}], "ok": True})
        self.assertTrue(result == {"items": [{}], "ok": True},
                        "Public projection retained a private field or credential key")

    def test_audit_metadata_rejects_each_token_family_without_printing_values(self):
        from datetime import UTC, datetime

        from nonzero_cloudops.models import (
            AuditEventType,
            generate_event_id,
            generate_run_id,
        )

        for prefix in ("ghp", "gho", "ghu", "ghs", "ghr", "github_pat"):
            rejected = False
            try:
                AuditEvent(
                    event_id=generate_event_id(), run_id=generate_run_id(),
                    type=next(iter(AuditEventType)), timestamp=datetime.now(UTC),
                    source="synthetic-test", redacted_payload_hash="0" * 64,
                    metadata={"message": synthetic_credential(prefix)},
                )
            except ValueError:
                rejected = True
            self.assertTrue(rejected, "Audit accepted synthetic credential material")


@unittest.skipUnless(authority_fixture.AVAILABLE, "NonZero optional extra is not installed")
class RunScopedPortableExecutionTests(unittest.TestCase):
    def setUp(self):
        self.core = authority_fixture.NativeOperatorAuthorityTests()
        self.core.setUp()
        self.addCleanup(self.core.tearDown)

    @property
    def service(self):
        return self.core.app.runtime.nonzero_cloudops

    def complete(self):
        started = self.core.native_api(
            "POST", "/api/nonzero/runs", authority_fixture.TARGET, expected=201,
        )
        self.assertEqual(started["final_state"], "AWAITING_APPROVAL")
        path = "/api/nonzero/runs/" + started["run_id"]
        self.core.approve(path)
        result = self.core.resume(path)
        self.assertEqual(result["final_state"], "SUCCESS_WITH_EVIDENCE")
        return path, result

    def test_new_execution_keys_include_run_identity(self):
        _, result = self.complete()
        self.assertEqual(
            result["receipt"]["idempotency_key"],
            "local-exec:" + result["run_id"] + ":" + result["receipt"]["proposal_hash"],
        )

    def test_completed_demo_can_run_again_without_colliding_or_replaying(self):
        path, first = self.complete()
        first_receipt = first["receipt"]
        self.core.restart_core()
        _, second = self.complete()
        self.assertNotEqual(first["run_id"], second["run_id"])
        self.assertNotEqual(first_receipt["idempotency_key"], second["receipt"]["idempotency_key"])
        inventory = self.service.components.inventory
        self.assertEqual(
            inventory.get_receipt(first_receipt["idempotency_key"]).receipt_hash,
            first_receipt["receipt_hash"],
        )
        self.assertEqual(self.service.components.executor.mutation_calls, 1)
        replay = self.core.resume(path)
        self.assertEqual(replay["receipt"], first_receipt)
        self.assertEqual(self.service.components.executor.mutation_calls, 1)
        self.assertEqual(self.core.app.runtime._owned_cpl_fixture.requests, [])

    def test_legacy_intent_and_receipt_survive_restart_without_reexecution(self):
        # Input fixture for the historical wire format; all actual authority,
        # execution, durable stores and restart/readback remain unmocked.
        with historical_intent_format():
            path, first = self.complete()
        self.core.restart_core()
        result = self.core.resume(path)
        self.assertEqual(result["receipt"], first["receipt"])
        self.assertEqual(self.service.components.executor.mutation_calls, 0)
        checkpoint = self.service.components.repository.get_checkpoint(UUID(first["run_id"]))
        self.assertEqual(checkpoint.local_execution_intent.idempotency_key,
                         "local-exec:" + first["receipt"]["proposal_hash"])

    def test_consumed_but_unverified_resource_cannot_be_rearmed(self):
        from nonzero_cloudops.adapters.portable import PortableConflictError

        path = self.core.start_run()
        self.core.approve(path)
        executor = self.service.components.executor
        with patch.object(executor, "verify", side_effect=PortableConflictError):
            self.core.resume(path, expected=422)
        inventory = self.service.components.inventory
        before = hashlib.sha256(inventory.path.read_bytes()).hexdigest()
        self.core.native_api("POST", "/api/nonzero/runs", authority_fixture.TARGET, expected=409)
        self.assertEqual(hashlib.sha256(inventory.path.read_bytes()).hexdigest(), before)
        self.assertEqual(executor.mutation_calls, 1)

    def test_untrusted_start_cannot_restore_consumed_inventory(self):
        from nonzero_cloudops import NonZeroError
        from nonzero_cloudops.views import StartRunRequest

        self.complete()
        inventory = self.service.components.inventory
        before = inventory.path.read_bytes()
        with self.assertRaises(NonZeroError):
            self.service.start(StartRunRequest(**authority_fixture.TARGET))
        self.assertEqual(inventory.path.read_bytes(), before)

    def test_cross_run_intent_cannot_reuse_legacy_or_new_key(self):
        from nonzero_cloudops.adapters.portable import PortablePolicyError
        from nonzero_cloudops.models import Checkpoint, generate_run_id

        _, result = self.complete()
        checkpoint = self.service.components.repository.get_checkpoint(UUID(result["run_id"]))
        inventory = self.service.components.inventory
        before = inventory.path.read_bytes()
        for key in (checkpoint.local_execution_intent.idempotency_key,
                    "local-exec:" + checkpoint.remediation_proposal.proposal_hash):
            values = checkpoint.local_execution_intent.model_dump()
            values.update(run_id=generate_run_id(), idempotency_key=key)
            provisional = LocalExecutionIntent.model_construct(**values)
            values["intent_hash"] = compute_evidence_digest(provisional.binding_payload())
            altered = LocalExecutionIntent(**values)
            wire = checkpoint.model_dump()
            wire["local_execution_intent"] = altered
            with self.assertRaises(ValueError):
                Checkpoint.model_validate(wire)
            with self.assertRaises(PortablePolicyError):
                inventory.execute(proposal=checkpoint.remediation_proposal, evidence=checkpoint.resource_evidence,
                                  approval=checkpoint.local_approval, intent=altered,
                                  executed_at=self.core.now)
            self.assertEqual(inventory.path.read_bytes(), before)

    def test_old_success_cannot_hide_later_unverified_release_after_clock_regression(self):
        from datetime import timedelta

        from nonzero_cloudops.adapters.portable import PortableConflictError

        self.complete()
        self.core.now -= timedelta(minutes=1)
        started = self.core.native_api("POST", "/api/nonzero/runs", authority_fixture.TARGET, expected=201)
        path = "/api/nonzero/runs/" + started["run_id"]
        self.core.approve(path)
        with patch.object(self.service.components.executor, "verify", side_effect=PortableConflictError):
            self.core.resume(path, expected=422)
        inventory = self.service.components.inventory
        before = inventory.path.read_bytes()
        self.core.native_api("POST", "/api/nonzero/runs", authority_fixture.TARGET, expected=409)
        self.assertEqual(inventory.path.read_bytes(), before)

    def test_rearm_requires_complete_bound_proofs_and_preserves_inventory_on_denial(self):
        from nonzero_cloudops.adapters.portable import (
            PortableConflictError,
            PortablePolicyError,
        )

        _, result = self.complete()
        inventory = self.service.components.inventory
        checkpoint = self.service.components.repository.get_checkpoint(UUID(result["run_id"]))
        query = ResourceQuery(**authority_fixture.TARGET)
        before = inventory.path.read_bytes()
        with self.assertRaises(PortableConflictError):
            inventory.rearm_verified_demo_resource(query, verifications=())
        proof = checkpoint.local_verification
        with self.assertRaises(PortableConflictError):
            inventory.rearm_verified_demo_resource(query, verifications=(proof, proof))
        with self.assertRaises(PortablePolicyError):
            inventory.rearm_verified_demo_resource(query, verifications=("receipt-only",))
        self.assertEqual(inventory.path.read_bytes(), before)

    def test_pending_sibling_blocks_rearm_until_explicit_human_denial(self):
        first = self.core.start_run()
        pending = self.core.start_run()
        self.core.approve(first)
        self.assertEqual(self.core.resume(first)["final_state"], "SUCCESS_WITH_EVIDENCE")
        inventory = self.service.components.inventory
        before = inventory.path.read_bytes()
        self.core.native_api("POST", "/api/nonzero/runs", authority_fixture.TARGET, expected=409)
        self.assertEqual(inventory.path.read_bytes(), before)
        self.assertEqual(self.service.components.repository.run_count(), 2)
        self.core.approve(pending, "DENIED")
        _, next_run = self.complete()
        self.assertEqual(next_run["final_state"], "SUCCESS_WITH_EVIDENCE")
        self.assertEqual(self.service.components.executor.mutation_calls, 2)

    def test_approved_sibling_cannot_use_a_rearmed_generation_after_restart(self):
        first = self.core.start_run()
        sibling = self.core.start_run()
        self.core.approve(first)
        self.core.approve(sibling)
        self.assertEqual(self.core.resume(first)["final_state"], "SUCCESS_WITH_EVIDENCE")
        self.core.restart_core()
        inventory = self.service.components.inventory
        before = inventory.path.read_bytes()
        self.core.native_api("POST", "/api/nonzero/runs", authority_fixture.TARGET, expected=409)
        self.assertEqual(inventory.path.read_bytes(), before)
        self.assertEqual(self.service.components.repository.run_count(), 2)
        self.assertEqual(self.core.native_api("GET", sibling)["run"]["state"], "APPROVED")
        self.core.resume(sibling, expected=409)  # Absence cannot become a new grant.
        self.assertEqual(self.service.components.executor.mutation_calls, 0)
        self.core.native_api("POST", "/api/nonzero/runs", authority_fixture.TARGET, expected=409)
        self.assertEqual(inventory.path.read_bytes(), before)

    def test_unrelated_pending_target_does_not_block_verified_demo_rearm(self):
        pending = self.core.start_run(authority_fixture.GROUP)
        self.complete()
        self.complete()
        self.assertEqual(self.core.native_api("GET", pending)["run"]["state"], "AWAITING_APPROVAL")
        self.assertEqual(self.service.components.executor.mutation_calls, 2)

    def test_stop_and_closed_lease_deny_demo_rearm(self):
        from nonzero_cloudops import NonZeroError
        from nonzero_cloudops.views import StartRunRequest

        self.complete()
        service = self.service
        inventory = service.components.inventory
        before = inventory.path.read_bytes()
        request = StartRunRequest(**authority_fixture.TARGET)
        with patch.object(service, "_guard", return_value=True), self.assertRaises(NonZeroError):
            service.start(request, operator=True)
        self.assertEqual(inventory.path.read_bytes(), before)
        service.close()
        with self.assertRaises(NonZeroError):
            service.start(request, operator=True)
        self.assertEqual(inventory.path.read_bytes(), before)

    def test_public_evidence_chain_never_stores_nested_credentials(self):
        service = self.service
        value = synthetic_credential("ghr")
        service._evidence.append("synthetic_projection", {"detail": [value]})
        entries, result = service._evidence.check()
        self.assertTrue(result.ok)
        rendered = json.dumps(entries)
        self.assertTrue(value not in rendered, "Credential survived durable Core projection")
        self.assertIn("[REDACTED]", rendered)
        # Existing reader stays bound to the same inventory and makes no network call.
        self.assertIsNotNone(service.components.reader.get_resource(ResourceQuery(**authority_fixture.TARGET)))
        self.assertEqual(service.components.reader.network_calls, 0)
