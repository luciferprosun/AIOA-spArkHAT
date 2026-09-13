"""Independent wire/privacy tests; never use durable DTO equality as privacy proof."""

from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from test_memory_patch_lifecycle import MemoryFixture, memory_hat_manifest
from test_memory_patch_persistence_ports import make_admission

from runtime.core_admission import Capability
from runtime.main import AgentRuntime
from runtime.memory_patch.contract import (
    OPERATOR_INTENT,
    MemoryPatchConfig,
    operation_capability,
)
from runtime.memory_patch.contracts.enums import MemoryContentKind
from runtime.memory_patch.correction.answers import NativeVerifiedAnswer
from runtime.memory_patch.errors import ErrorCode, MemoryPatchError
from runtime.memory_patch.persistence.ports import RecordKind
from runtime.memory_patch.service import CoreMemoryPatchDependencies, MemoryPatchService
from runtime.memory_patch.views import (
    ProjectionContext,
    envelope,
    error_response,
    verified_answer_view,
)
from runtime.webapp import WebRuntimeService, make_server

FORBIDDEN_KEYS = frozenset(
    {
        "tenantid",
        "ownerid",
        "userid",
        "actorid",
        "actorsessionid",
        "noncehash",
        "sessiontoken",
        "approvalhash",
        "contenthash",
        "candidatedigest",
        "authorizationbinding",
        "sourceapproval",
        "sourcecommit",
        "approvalreceipt",
        "commitreceipt",
        "audit",
        "outbox",
        "payload",
        "traceback",
        "password",
        "dsn",
        "connectionstring",
        "evidencechain",
        "recorddigest",
        "manifestdigest",
        "supersedesprivateid",
        "requesthash",
        "bundlehash",
        "packet",
        "verification",
        "operationkey",
    }
)
ENVELOPE_KEYS = {"ok", "module", "operation", "result", "error"}
PATCH_KEYS = {
    "patch_id",
    "revision",
    "state",
    "title",
    "summary",
    "created_at",
    "updated_at",
    "validity",
    "source_refs",
    "verification_status",
    "allowed_actions",
}


def assert_private(test, value, secrets, *, nonce=None, path=()):
    """Failures contain a field path only, never a protected test value."""
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = "".join(c for c in key.casefold() if c.isalnum())
            if normalized in FORBIDDEN_KEYS:
                test.fail("private key at " + ".".join((*path, key)))
            if normalized == "decisionnonce" and (*path, key) != (
                "result",
                "decision_nonce",
            ):
                test.fail("nonce outside challenge at " + ".".join((*path, key)))
            assert_private(test, child, secrets, nonce=nonce, path=(*path, key))
    elif isinstance(value, (tuple, list)):
        for index, child in enumerate(value):
            assert_private(test, child, secrets, nonce=nonce, path=(*path, str(index)))
    elif isinstance(value, str):
        if (
            nonce is not None
            and path == ("result", "decision_nonce")
            and value == nonce
        ):
            return
        if any(secret and secret.casefold() in value.casefold() for secret in secrets):
            test.fail("private value at " + ".".join(path))


class TransportFixture:
    def __init__(self):
        self.fx = MemoryFixture()
        self.private = "private-value-under-harmless-title"
        f = self.fx
        self.config = MemoryPatchConfig(True, f.core._assignment)
        self.dependencies = CoreMemoryPatchDependencies(
            transaction_factory=f.factory,
            evidence_catalog=f.rf.catalog,
            sources=f.rf.sources,
            bundle_resolver=f.evidence.resolver,
            provenance_store=f.store,
            hat_manifests=(memory_hat_manifest(),),
            quota=f.quota,
            freshness=f.rf.service.freshness,
            private_values=(self.private,),
            clock=lambda: f.now,
        )
        self.provider = Mock()
        self.directory = tempfile.TemporaryDirectory()
        self.runtime = AgentRuntime(
            self.provider,
            "fixture",
            Path(self.directory.name),
            memory_patch_config=self.config,
            memory_patch_dependencies=self.dependencies,
        )
        # This is an explicit synthetic Core injection, sharing the existing
        # authority/session with the domain fixture. It is never JSON input.
        self.runtime._memory_patch_admission = f.core
        self.runtime.hat_store = f.selection

    def request(self, op, body=None):
        return self.runtime.memory_patch_operator_request(
            op, {} if body is None else body
        )

    def secrets(self, *extra):
        f = self.fx
        return (
            *f.core._assignment.scope.binding(),
            f.core._session,
            self.private,
            *f.core._assignment.hat_ids,
            *f.core._assignment.model_binding_ids,
            *(r.payload_digest for r in f.factory.state.values()),
            *extra,
        )

    def close(self):
        self.runtime.close()
        self.fx.close()
        self.directory.cleanup()


class PublicViewsTests(unittest.TestCase):
    def setUp(self):
        self.tf = TransportFixture()
        self.addCleanup(self.tf.close)

    def request(self, op, body=None, *, success=True):
        status, value = self.tf.request(op, body)
        self.assertEqual(ENVELOPE_KEYS, set(value))
        self.assertEqual(success, value["ok"], value.get("error"))
        self.assertEqual(success, status < 400)
        assert_private(self, value, self.tf.secrets())
        return value

    def prepared(self, *, draft=None, key="wire"):
        return self.tf.fx.prepare(draft, key=key)

    def test_status_is_closed_inert_and_cli_matches_http_service(self):
        value = self.request("status")
        self.assertEqual(
            {
                "module_id",
                "contract_version",
                "available",
                "enabled",
                "backend_status",
                "reason_code",
            },
            set(value["result"]),
        )
        self.assertIsNone(self.tf.runtime._memory_patch_service)
        result = self.tf.runtime.command_registry.execute(
            "/memory-patch status", self.tf.runtime
        )
        self.assertEqual(value, json.loads(result.message))
        self.tf.provider.assert_not_called()

    def test_owner_content_and_sources_use_closed_nested_views(self):
        patch_id = self.tf.fx.activate()
        value = self.request("read", {"patch_id": patch_id})["result"]
        self.assertEqual(PATCH_KEYS, set(value))
        self.assertEqual("VERIFIED", value["verification_status"])
        self.assertEqual(
            {"valid_from", "valid_until", "expires_at"}, set(value["validity"])
        )
        self.assertTrue(value["source_refs"])
        for source in value["source_refs"]:
            self.assertEqual({"evidence_id"}, set(source))
        self.request("list")
        self.request("trace", {"patch_id": patch_id})
        self.request("recover", {"patch_id": patch_id})

    def test_sensitive_values_under_harmless_keys_and_mixed_case_are_withheld(self):
        for index, secret in enumerate(
            (
                self.tf.private,
                self.tf.fx.core._session,
                self.tf.fx.core._assignment.scope.owner_id,
                "postgresql://private.invalid/database",
                "/home/private/key",
            )
        ):
            with self.subTest(case=index):
                draft = self.tf.fx.draft(
                    title=secret.upper(),
                    summary=secret.upper(),
                    content_kind=MemoryContentKind.WORKFLOW,
                )
                patch_id = self.tf.fx.detect(draft, key="seed-" + str(index))
                value = self.request("read", {"patch_id": patch_id})
                assert_private(self, value, (secret,))
                self.assertEqual("UNVERIFIED", value["result"]["verification_status"])
                self.assertEqual([], value["result"]["allowed_actions"])

    def test_raw_nonce_exists_only_on_fresh_challenge_and_never_in_durable_rows(self):
        patch_id = self.prepared()
        body = {
            "patch_id": patch_id,
            "expected_revision": 5,
            "operation_key": "fresh-wire",
        }
        status, value = self.tf.request("challenge", body)
        self.assertEqual(200, status, value["error"])
        raw = value["result"]["decision_nonce"]
        self.assertIsInstance(raw, str)
        assert_private(self, value, self.tf.secrets(raw), nonce=raw)
        for record in self.tf.fx.factory.state.values():
            self.assertNotIn(raw, str(record.payload), "nonce persisted")
        replay = self.request("challenge", body)
        self.assertIsNone(replay["result"]["decision_nonce"])
        decision = {
            "challenge_id": value["result"]["challenge_id"],
            "expected_revision": 5,
            "decision": "APPROVE",
            "decision_nonce": raw,
            "operation_key": "wire-decision",
        }
        approved = self.request("decision", decision)
        self.assertEqual("APPROVED", approved["result"]["state"])
        assert_private(self, approved, self.tf.secrets(raw))
        self.assertEqual(approved, self.request("decision", decision))
        self.request("read", {"patch_id": patch_id})
        self.assertEqual(1, len(self.tf.fx.rows(RecordKind.APPROVAL)))

    def test_reject_stays_durable_and_does_not_activate(self):
        patch_id = self.prepared()
        challenge = self.request(
            "challenge",
            {
                "patch_id": patch_id,
                "expected_revision": 5,
                "operation_key": "reject-challenge",
            },
        )["result"]
        self.request(
            "decision",
            {
                "challenge_id": challenge["challenge_id"],
                "expected_revision": 5,
                "decision": "REJECT",
                "decision_nonce": challenge["decision_nonce"],
                "operation_key": "reject-decision",
            },
        )
        self.assertEqual("REJECTED", self.tf.fx.read(patch_id).payload["state"])
        self.assertEqual([], self.tf.fx.rows(RecordKind.RECEIPT))

    def test_old_activation_replay_after_revoke_reports_current_revoked_state(self):
        patch_id = self.prepared()
        self.tf.fx.approve(patch_id)
        self.tf.fx.publish()
        self.request(
            "commit",
            {
                "patch_id": patch_id,
                "expected_revision": 6,
                "operation_key": "wire-commit",
            },
        )
        body = {
            "patch_id": patch_id,
            "expected_revision": 7,
            "operation_key": "wire-activate",
        }
        active = self.request("activate", body)
        self.assertEqual("ACTIVE", active["result"]["state"])
        self.request(
            "revoke",
            {
                "patch_id": patch_id,
                "expected_revision": 8,
                "operation_key": "wire-revoke",
            },
        )
        replay = self.request("activate", body)
        self.assertEqual("REVOKED", replay["result"]["state"])
        self.assertEqual(9, replay["result"]["revision"])
        self.assertNotEqual("VERIFIED", replay["result"]["verification_status"])
        self.assertEqual(2, len(self.tf.fx.rows(RecordKind.RECEIPT)))

    def test_lost_challenge_is_replaced_and_old_nonce_is_denied(self):
        patch_id = self.prepared()
        first = self.request(
            "challenge",
            {"patch_id": patch_id, "expected_revision": 5, "operation_key": "lost-1"},
        )["result"]
        self.request(
            "challenge",
            {"patch_id": patch_id, "expected_revision": 5, "operation_key": "lost-2"},
        )
        self.request(
            "decision",
            {
                "challenge_id": first["challenge_id"],
                "expected_revision": 5,
                "decision": "APPROVE",
                "decision_nonce": first["decision_nonce"],
                "operation_key": "lost-reuse",
            },
            success=False,
        )
        self.assertEqual([], self.tf.fx.rows(RecordKind.APPROVAL))

    def test_wrong_owner_and_request_identity_flags_never_grant_access(self):
        patch_id = self.tf.fx.activate()
        self.request("read", {"patch_id": patch_id})
        service = self.tf.runtime._memory_patch_service
        other = make_admission(owner="different-private-owner")
        status, value = service.request(
            other.local_operator(Capability.READ), "read", {"patch_id": patch_id}
        )
        self.assertEqual(403, status)
        assert_private(self, value, self.tf.secrets("different-private-owner"))
        for name in (
            "operator",
            "owner_id",
            "tenant_id",
            "actor_session_id",
            "principal",
        ):
            self.request("read", {"patch_id": patch_id, name: True}, success=False)

    def test_restart_readback_does_not_reuse_old_challenge_authority(self):
        patch_id = self.prepared()
        challenge = self.request(
            "challenge",
            {
                "patch_id": patch_id,
                "expected_revision": 5,
                "operation_key": "restart-challenge",
            },
        )["result"]
        self.tf.fx.restart()
        self.tf.runtime._memory_patch_admission = self.tf.fx.core
        self.tf.runtime._memory_patch_service.close()
        self.tf.runtime._memory_patch_service = None
        self.request(
            "decision",
            {
                "challenge_id": challenge["challenge_id"],
                "expected_revision": 5,
                "decision": "APPROVE",
                "decision_nonce": challenge["decision_nonce"],
                "operation_key": "restart-decision",
            },
            success=False,
        )
        self.request("trace", {"patch_id": patch_id})
        self.request("recover", {"patch_id": patch_id})

    def test_unknown_commit_and_publication_failure_are_bounded_errors(self):
        self.request("list")
        service = self.tf.runtime._memory_patch_service
        self.tf.fx.factory.commit_faults = ["unknown_after_commit"]
        error = self.request(
            "candidate",
            {
                "title": "Private context",
                "summary": "Owner-provided context.",
                "body": "Owner-provided context.",
                "content_kind": "WORKFLOW",
                "hat_id": "test-hat",
                "operation_key": "uncertain-candidate",
            },
            success=False,
        )
        self.assertEqual("RECOVERY_REQUIRED", error["error"]["code"])
        self.assertTrue(error["error"]["recovery_required"])
        with patch.object(
            service.lifecycle,
            "publish_pending",
            side_effect=MemoryPatchError(ErrorCode.PROVENANCE_PENDING),
        ):
            pending = self.request(
                "candidate",
                {
                    "title": "Another context",
                    "summary": "Another owner context.",
                    "body": "Another owner context.",
                    "content_kind": "WORKFLOW",
                    "hat_id": "test-hat",
                    "operation_key": "pending-candidate",
                },
                success=False,
            )
        self.assertEqual("PROVENANCE_PENDING", pending["error"]["code"])

    def test_changed_verified_answer_is_downgraded(self):
        p = self.tf.fx.p(Capability.READ)
        ctx = ProjectionContext(self.tf.fx.core, p, (self.tf.private,))
        answer = NativeVerifiedAnswer(
            self.tf.private.upper(), "VERIFIED", (), False, False, object(), 1
        )
        value = envelope(
            "answer", result=verified_answer_view(ctx, answer, citations=())
        )
        self.assertEqual("UNVERIFIED", value["result"]["status"])
        self.assertTrue(value["result"]["review_required"])
        assert_private(self, value, self.tf.secrets())

    def test_export_sharing_and_review_do_not_export_durable_authority(self):
        patch_id = self.tf.fx.activate()
        exported = self.request("export", {"operation_key": "wire-export"})
        self.assertEqual(1, len(exported["result"]["patches"]))
        sharing = self.request(
            "sharing",
            {
                "patch_id": patch_id,
                "expected_revision": 8,
                "consent": True,
                "deidentified_summary": self.tf.private,
                "operation_key": "wire-sharing",
            },
        )
        self.assertEqual("DOMAIN_REVIEW_REQUIRED", sharing["result"]["state"])
        opened = self.request(
            "review-open",
            {
                "patch_id": patch_id,
                "expected_revision": 8,
                "operation_key": "wire-case",
            },
        )
        case_id = opened["result"]["case_id"]
        self.request("review-queue")
        self.request(
            "review-claim",
            {"case_id": case_id, "expected_revision": 1, "operation_key": "wire-claim"},
        )
        self.request(
            "review-decision",
            {
                "case_id": case_id,
                "expected_revision": 2,
                "decision": "ACCEPT_ADVISORY",
                "operation_key": "wire-review",
            },
        )
        self.assertEqual("ACTIVE", self.tf.fx.read(patch_id).payload["state"])

    def test_all_error_types_discard_messages_and_unknown_operation_echo(self):
        for code in ErrorCode:
            _, value = error_response(self.tf.private, MemoryPatchError(code))
            self.assertEqual("invalid", value["operation"])
            assert_private(self, value, self.tf.secrets())
        for error in (
            RuntimeError(self.tf.private),
            ValueError(self.tf.private),
            OSError(self.tf.private),
        ):
            _, value = error_response("read", error)
            assert_private(self, value, self.tf.secrets())

    def test_cli_malformed_json_and_duplicate_keys_are_closed(self):
        for text in (
            'candidate {"operator":true}',
            'status {"x":1,"x":2}',
            'status {"x":NaN}',
            "status []",
            "status " + "[" * 1200,
            self.tf.private + " {}",
        ):
            output = self.tf.runtime.command_registry.execute(
                "/memory-patch " + text, self.tf.runtime
            )
            value = json.loads(output.message)
            self.assertFalse(value["ok"])
            assert_private(self, value, self.tf.secrets())

    def test_borrowed_resources_are_not_closed(self):
        self.request("list")
        service = self.tf.runtime._memory_patch_service
        with patch.object(self.tf.fx.factory, "close") as close:
            service.close()
            service.close()
            close.assert_not_called()
        status, value = service.request(None, "status", {})
        self.assertEqual(503, status)
        self.assertEqual("MODULE_CLOSED", value["error"]["code"])

    def test_complete_command_pipeline_and_separate_retrieval_lane(self):
        f = self.tf.fx
        f.factory.state.clear()  # Explicit empty fake, never a database or user state.
        self.request("slot-create", {"operation_key": "fresh-slot"})
        self.request(
            "slot-configure",
            {
                "hat_id": "test-hat",
                "expected_revision": 1,
                "operation_key": "fresh-config",
            },
        )
        self.request(
            "slot-state",
            {
                "state": "ACTIVE",
                "expected_revision": 2,
                "operation_key": "fresh-slot-active",
            },
        )
        draft = f.draft()
        detected = self.request(
            "candidate",
            {
                "title": draft.title,
                "summary": draft.summary,
                "body": draft.body,
                "content_kind": draft.content_kind.value,
                "hat_id": draft.hat_id,
                "evidence_references": list(draft.evidence_references),
                "operation_key": "fresh-candidate",
            },
        )
        patch_id = detected["result"]["patch_id"]
        for revision, op in enumerate(
            ("propose", "bind-evidence", "validate", "await-approval"), 1
        ):
            self.request(
                op,
                {
                    "patch_id": patch_id,
                    "expected_revision": revision,
                    "operation_key": "fresh-" + op,
                },
            )
        challenge = self.request(
            "challenge",
            {
                "patch_id": patch_id,
                "expected_revision": 5,
                "operation_key": "fresh-challenge",
            },
        )["result"]
        self.request(
            "decision",
            {
                "challenge_id": challenge["challenge_id"],
                "expected_revision": 5,
                "decision": "APPROVE",
                "decision_nonce": challenge["decision_nonce"],
                "operation_key": "fresh-decision",
            },
        )
        self.request(
            "commit",
            {
                "patch_id": patch_id,
                "expected_revision": 6,
                "operation_key": "fresh-commit",
            },
        )
        self.request(
            "activate",
            {
                "patch_id": patch_id,
                "expected_revision": 7,
                "operation_key": "fresh-activation",
            },
        )
        retrieved = self.request(
            "retrieve", {"hat_id": "test-hat", "query": "reviewed rule"}
        )
        self.assertEqual(
            [patch_id], [item["patch_id"] for item in retrieved["result"]["patches"]]
        )
        self.assertEqual(1, f.rf.catalog.admissions)
        self.request(
            "revoke",
            {
                "patch_id": patch_id,
                "expected_revision": 8,
                "operation_key": "fresh-revoke",
            },
        )
        self.assertEqual(
            [],
            self.request("retrieve", {"hat_id": "test-hat", "query": "reviewed rule"})[
                "result"
            ]["patches"],
        )

    def test_exact_core_provider_answer_replay_uses_same_packet_and_no_second_call(
        self,
    ):
        from test_memory_patch_critic import ExactProviderTests

        provider_fixture = ExactProviderTests()
        provider_fixture.setUp()
        d = replace(
            self.tf.dependencies,
            provider_binding=provider_fixture.binding,
            packet_key=b"explicit-synthetic-core-packet-key" * 2,
        )
        service = MemoryPatchService(
            self.tf.fx.core,
            config=self.tf.config,
            dependencies=d,
            existing_provider_manager=provider_fixture.manager,
            existing_hat_selection=self.tf.fx.selection,
        )
        self.addCleanup(service.close)
        body = {
            "hat_id": "test-hat",
            "query": "reviewed rule",
            "draft": "The reviewed policy applies.",
            "operation_key": "answer-wire",
        }
        p = self.tf.fx.p(operation_capability("answer"))
        first = service.request(p, "answer", body)
        self.assertEqual(200, first[0], first[1]["error"])
        self.assertEqual("VERIFIED", first[1]["result"]["status"])
        assert_private(self, first[1], self.tf.secrets())
        self.assertEqual(first, service.request(p, "answer", body))
        self.assertEqual(1, len(provider_fixture.manager.requests))
        status, denied = service.request(
            p, "answer", {**body, "draft": "Different draft."}
        )
        self.assertEqual(409, status)
        self.assertEqual("IDEMPOTENCY_CONFLICT", denied["error"]["code"])
        self.assertEqual(1, len(provider_fixture.manager.requests))

    def test_migration_plan_is_private_and_c4_execution_is_denied(self):
        from test_memory_patch_discovery import MigrationContractTests

        fixture = MigrationContractTests()
        fixture.setUp()
        service = MemoryPatchService(
            self.tf.fx.core,
            config=self.tf.config,
            dependencies=replace(self.tf.dependencies, migration_plans=(fixture.plan,)),
        )
        self.addCleanup(service.close)
        p = self.tf.fx.p(Capability.MIGRATE)
        status, view = service.request(
            p, "migration-plan", {"plan_id": fixture.plan.plan_id}
        )
        self.assertEqual(200, status)
        self.assertIs(False, view["result"]["executable"])
        assert_private(
            self,
            view,
            self.tf.secrets(
                fixture.target.database,
                fixture.target.host,
                fixture.target.application_role,
            ),
        )
        self.assertEqual(
            403, service.request(p, "migrate", {"plan_id": fixture.plan.plan_id})[0]
        )

    def test_legacy_core_provenance_import_reuses_the_same_injected_store(self):
        from tools.provenance import AppendOnlyProvenanceStore

        from runtime.memory_patch.audit import CoreLedgerPublication

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "provenance").mkdir(mode=0o700)
            existing = AppendOnlyProvenanceStore(root)
            publication = CoreLedgerPublication(self.tf.fx.core, existing)
            self.assertIs(existing, publication._store)
            publication.initialize(self.tf.fx.p(Capability.MANAGE))


class ExistingCoreHttpTests(unittest.TestCase):
    def setUp(self):
        self.tf = TransportFixture()
        self.addCleanup(self.tf.close)
        self.web = WebRuntimeService(runtime=self.tf.runtime)
        self.server = make_server("127.0.0.1", 0, service=self.web)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(5)

    def http(self, path, body=None, *, headers=None, method=None, raw=None):
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.server.server_address[1], timeout=5
        )
        supplied = {
            "X-AIOA-Session-Token": self.web.csrf_token,
            "X-AIOA-Intent": OPERATOR_INTENT,
        }
        if headers is not None:
            supplied.update(headers)
            supplied = {k: v for k, v in supplied.items() if v is not None}
        method = method or ("GET" if body is None and raw is None else "POST")
        wire = raw if raw is not None else None if body is None else json.dumps(body)
        try:
            connection.request(method, path, body=wire, headers=supplied)
            response = connection.getresponse()
            value = json.loads(response.read())
            self.assertEqual("no-store", response.getheader("Cache-Control"))
            self.assertEqual(ENVELOPE_KEYS, set(value))
            assert_private(self, value, self.tf.secrets(self.web.csrf_token))
            return response.status, value
        finally:
            connection.close()

    def test_host_origin_session_and_intent_precede_module_initialization(self):
        for header in (
            {"Host": "malicious.invalid"},
            {"Origin": "https://malicious.invalid"},
            {"Sec-Fetch-Site": "cross-site"},
            {"X-AIOA-Session-Token": None},
            {"X-AIOA-Session-Token": "invalid"},
            {"X-AIOA-Intent": None},
            {"X-AIOA-Intent": "nonzero-operator-v1"},
        ):
            status, result = self.http("/api/memory-patch/list", headers=header)
            self.assertEqual(403, status)
            self.assertFalse(result["ok"])
            self.assertIsNone(self.tf.runtime._memory_patch_service)

    def test_valid_status_stays_inert_and_owner_read_matches_cli(self):
        self.assertEqual(200, self.http("/api/memory-patch/status")[0])
        self.assertIsNone(self.tf.runtime._memory_patch_service)
        patch_id = self.tf.fx.activate()
        body = {"patch_id": patch_id}
        status, read = self.http("/api/memory-patch/read", body)
        self.assertEqual(200, status, read["error"])
        cli = self.tf.runtime.command_registry.execute(
            "/memory-patch read " + json.dumps(body), self.tf.runtime
        )
        self.assertEqual(read, json.loads(cli.message))

    def test_malformed_paths_body_and_identity_fields_are_denied(self):
        for path in (
            "/api/memory-patch",
            "/api/memory-patch/status?nonce=private",
            "/api/memory-patch%2Fread",
            "/api/memory-patch/read/extra",
            "/api/memory-patch/" + self.tf.private,
        ):
            self.assertGreaterEqual(self.http(path)[0], 400)
            self.assertIsNone(self.tf.runtime._memory_patch_service)
        for raw in ('{"x":1,"x":2}', '{"x":NaN}', "[]", "{broken", "[" * 1200):
            self.assertGreaterEqual(
                self.http("/api/memory-patch/status", raw=raw)[0], 400
            )
            self.assertIsNone(self.tf.runtime._memory_patch_service)
        status, _ = self.http(
            "/api/memory-patch/slot-create",
            {"operation_key": "never", "operator": True},
        )
        self.assertEqual(400, status)
        self.assertIsNone(self.tf.runtime._memory_patch_service)

    def test_chat_cannot_obtain_memory_operator_authority(self):
        from providers.exact import ExactCallError

        for mode in ("plain", "cpl"):
            for separator in (" ", "\t", "\n"):
                with self.assertRaises(ExactCallError):
                    self.tf.runtime.assistant_request(
                        "/memory-patch" + separator + "slot-create {}", mode=mode
                    )
        self.assertIsNone(self.tf.runtime._memory_patch_service)
        self.tf.provider.assert_not_called()
