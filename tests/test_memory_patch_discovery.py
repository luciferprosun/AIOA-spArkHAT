from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import timedelta
from unittest.mock import Mock, patch

from test_memory_patch_persistence_ports import NOW, make_admission

from runtime.core_admission import AdmissionError, Capability
from runtime.memory_patch.errors import MemoryPatchError
from runtime.memory_patch.persistence.migration_contract import (
    DenyOnlyMigrationExecutor,
    JuryDenylist,
    MigrationAdmission,
    MigrationPlan,
    MigrationUnit,
    TargetAllowlist,
    TargetIdentity,
    canary_fingerprint,
    canonical_host,
    parse_target_uri,
)

SYNTHETIC_CANARIES = {
    "hostname": "never.fixture.invalid",
    "cluster_marker": "forbidden-cluster",
    "database": "aioa_disposable_forbidden",
    "account_id": "123456789012",
    "resource_arn": "arn:fixture:service:region:123456789012:blocked-resource",
}


def synthetic_denylist():
    return JuryDenylist(
        frozenset(
            (category, canary_fingerprint(category, value))
            for category, value in SYNTHETIC_CANARIES.items()
        )
    )


def target_fixture(**changes):
    fields = dict(
        host="localhost",
        address="127.0.0.1",
        port=26257,
        database="aioa_disposable_fixture",
        cluster_marker="local_fixture",
        application_role="fixture_app",
        migrator_role="fixture_migrator",
        certificate_fingerprint="c" * 64,
    )
    fields.update(changes)
    return TargetIdentity(**fields)


class MigrationContractTests(unittest.TestCase):
    def setUp(self):
        self.core = make_admission()
        self.principal = self.core.local_operator(Capability.MIGRATE)
        self.target = target_fixture()
        self.current = NOW
        self.admission = MigrationAdmission(
            self.core,
            TargetAllowlist(frozenset({self.target.fingerprint})),
            synthetic_denylist(),
            clock=lambda: self.current,
        )
        self.plan = MigrationPlan(
            "plan_0123456789abcdef",
            self.target,
            "Disposable fixture",
            "a" * 64,
            "b" * 64,
            (MigrationUnit(1, "0001_identity.sql", "d" * 64),),
        )

    def authorize(self):
        return self.admission.admit(
            self.principal, self.plan, disposable_ownership_confirmed=True
        )

    def test_plan_and_authorization_cannot_execute_in_c4(self):
        with (
            patch(
                "socket.create_connection",
                side_effect=AssertionError("connection attempted"),
            ),
            patch("socket.getaddrinfo", side_effect=AssertionError("DNS attempted")),
        ):
            authorization = self.authorize()
            with self.assertRaises(MemoryPatchError):
                DenyOnlyMigrationExecutor().execute(
                    self.principal, self.plan, authorization
                )

    def test_all_jury_canary_categories_fail_before_connector(self):
        alterations = {
            "hostname": {"host": SYNTHETIC_CANARIES["hostname"]},
            "cluster_marker": {"cluster_marker": SYNTHETIC_CANARIES["cluster_marker"]},
            "database": {"database": SYNTHETIC_CANARIES["database"]},
            "account_id": {"account_ids": (SYNTHETIC_CANARIES["account_id"],)},
            "resource_arn": {"resource_arns": (SYNTHETIC_CANARIES["resource_arn"],)},
        }
        connector = Mock()
        for category, changes in alterations.items():
            with self.subTest(category=category), self.assertRaises(MemoryPatchError):
                synthetic_denylist().require_clear(target_fixture(**changes))
                connector()
        connector.assert_not_called()

    def test_complete_cluster_label_prefix_is_denied(self):
        for host in (
            "forbidden-cluster.fixture.invalid",
            "forbidden-cluster-123.fixture.invalid",
        ):
            with self.assertRaises(MemoryPatchError):
                synthetic_denylist().require_clear(target_fixture(host=host))

    def test_exact_allowlist_binds_address_port_role_database_and_certificate(self):
        for changes in (
            {"address": "::1"},
            {"port": 26258},
            {"application_role": "changed_app"},
            {"database": "aioa_disposable_other"},
            {"certificate_fingerprint": "e" * 64},
        ):
            with (
                self.subTest(field=next(iter(changes))),
                self.assertRaises(MemoryPatchError),
            ):
                self.admission.check_target(target_fixture(**changes))

    def test_unknown_nonlocal_host_requires_explicit_disposable_approval(self):
        remote = target_fixture(host="fixture.invalid", address="192.0.2.1")
        allowlist = TargetAllowlist(frozenset({remote.fingerprint}))
        with self.assertRaises(MemoryPatchError):
            allowlist.require_allowed(remote)
        approved = replace(
            allowlist,
            approved_disposable_hosts=frozenset({("fixture.invalid", "192.0.2.1")}),
        )
        approved.require_allowed(remote)

    def test_localhost_address_is_literal_and_bound(self):
        with self.assertRaises(MemoryPatchError):
            target_fixture(address="192.0.2.1")
        with self.assertRaises(MemoryPatchError):
            target_fixture(address="localhost")
        self.assertEqual("localhost", canonical_host("LOCALHOST."))
        with self.assertRaises(MemoryPatchError):
            canonical_host("localhost..")

    def test_roles_database_and_unknown_identity_rejected(self):
        for changes in (
            {"migrator_role": "fixture_app"},
            {"application_role": "root"},
            {"database": "postgres"},
            {"database": ""},
            {"cluster_marker": ""},
            {"port": True},
        ):
            with (
                self.subTest(field=next(iter(changes))),
                self.assertRaises(MemoryPatchError),
            ):
                target_fixture(**changes)

    def parse(self, uri):
        return parse_target_uri(
            uri,
            address="127.0.0.1",
            cluster_marker="local_fixture",
            application_role="fixture_app",
            migrator_role="fixture_migrator",
            certificate_fingerprint="c" * 64,
        )

    def test_metadata_uri_parses_once_without_secret_resolution(self):
        self.assertEqual(
            self.target,
            self.parse("postgresql://localhost:26257/aioa_disposable_fixture"),
        )
        encoded = self.parse("postgresql://localhost:26257/aioa_disposable_%66ixture")
        self.assertEqual(self.target, encoded)

    def test_ambiguous_encoded_overridden_and_multihost_uris_denied(self):
        paths = [
            "postgresql://localhost:26257/aioa_disposable_fixture?host=never.fixture.invalid",
            "postgresql://localhost:26257/aioa_disposable_fixture?hostaddr=192.0.2.1",
            "postgresql://localhost:26257/aioa_disposable_fixture?options=x",
            "postgresql://localhost:26257/aioa_disposable_fixture?service=unknown",
            "postgresql://localhost:26257/aioa_disposable_fixture?servicefile=x",
            "postgresql://localhost:26257/aioa_disposable_fixture#fragment",
            "postgresql://localhost:26257,other:26257/aioa_disposable_fixture",
            "postgresql://user@localhost:26257/aioa_disposable_fixture",
            "postgresql://%2ftmp:26257/aioa_disposable_fixture",
            "postgresql://localhost:26257/aioa_disposable_%252fescape",
            "postgresql://localhost:26257/aioa_disposable_%2fescape",
            "postgresql://localhost/aioa_disposable_fixture",
            "postgresql:///aioa_disposable_fixture",
            "service=unapproved",
        ]
        for index, uri in enumerate(paths):
            with self.subTest(case=index), self.assertRaises(MemoryPatchError):
                self.parse(uri)

    def test_explicit_disposable_confirmation_and_core_migrator_purpose_required(self):
        with self.assertRaises(MemoryPatchError):
            self.admission.admit(
                self.principal, self.plan, disposable_ownership_confirmed=False
            )
        with self.assertRaises(AdmissionError):
            self.admission.admit(
                self.core.local_operator(Capability.READ),
                self.plan,
                disposable_ownership_confirmed=True,
            )

    def test_authorization_is_single_use_and_binds_exact_schema(self):
        authorization = self.authorize()
        with self.assertRaises(MemoryPatchError):
            self.admission.consume(
                self.principal,
                self.plan,
                authorization,
                observed_schema_fingerprint="e" * 64,
            )
        self.admission.consume(
            self.principal,
            self.plan,
            authorization,
            observed_schema_fingerprint="a" * 64,
        )
        with self.assertRaises(MemoryPatchError):
            self.admission.consume(
                self.principal,
                self.plan,
                authorization,
                observed_schema_fingerprint="a" * 64,
            )

    def test_plan_tamper_and_expired_authorization_deny(self):
        authorization = self.authorize()
        with self.assertRaises(MemoryPatchError):
            self.admission.consume(
                self.principal,
                replace(self.plan, expected_schema_fingerprint="e" * 64),
                authorization,
                observed_schema_fingerprint="a" * 64,
            )
        self.current += timedelta(minutes=5)
        with self.assertRaises(MemoryPatchError):
            self.admission.consume(
                self.principal,
                self.plan,
                authorization,
                observed_schema_fingerprint="a" * 64,
            )

    def test_incomplete_canary_manifest_is_not_a_permissive_default(self):
        with self.assertRaises(MemoryPatchError):
            JuryDenylist(frozenset())
        with self.assertRaises(MemoryPatchError):
            JuryDenylist.from_manifest({"schema": "jury-canary-v1", "fingerprints": []})


class NativeDiscoveryTests(unittest.TestCase):
    def test_dependency_free_import_and_ambient_dsns_cannot_load_drivers_or_connect(
        self,
    ):
        import os
        import subprocess
        import sys

        code = """
import sys,socket
def forbidden(*a,**k):raise AssertionError("network or database attempt")
socket.create_connection=forbidden
socket.socket.connect=forbidden
socket.getaddrinfo=forbidden
import runtime.memory_patch as module
assert module.module_descriptor()["backend_status"] == "UNCONFIGURED"
assert not any(name.split(".")[0] in {"psycopg","psycopg2","asyncpg","pydantic","transformers","openai","anthropic"} for name in sys.modules)
assert "runtime.memory_patch.service" not in sys.modules
print("inert")
"""
        env = {
            **os.environ,
            "DATABASE_URL_MIGRATOR": "postgresql://never.fixture.invalid/no_connection",
            "DATABASE_URL_APP": "postgresql://never.fixture.invalid/no_connection",
            "OPENAI_API_KEY": "synthetic-unused",
            "ANTHROPIC_API_KEY": "synthetic-unused",
            "MEMORY_PATCH_ENABLED": "true",
            "MEMORY_PATCH_OPERATOR": "true",
        }
        result = subprocess.run(
            [sys.executable, "-B", "-c", code],
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(0, result.returncode, "isolated discovery failed")
        self.assertEqual("inert", result.stdout.strip())

    def test_core_startup_help_status_and_close_do_not_initialize_native_module(self):
        import tempfile
        from pathlib import Path

        from runtime.main import AgentRuntime
        from runtime.memory_patch.contract import MemoryPatchConfig

        with (
            tempfile.TemporaryDirectory() as directory,
            patch("socket.create_connection") as connect,
        ):
            manager = Mock()
            runtime = AgentRuntime(
                manager,
                "fixture",
                Path(directory),
                memory_patch_config=MemoryPatchConfig(),
            )
            try:
                self.assertIn("memory-patch", runtime.command_registry.names())
                self.assertIn(
                    "/memory-patch",
                    runtime.command_registry.execute("/help", runtime).message,
                )
                self.assertFalse(runtime.memory_patch_status()["enabled"])
                runtime.memory_patch_operator_request("status", {})
                self.assertIsNone(runtime._memory_patch_service)
                self.assertIsNone(runtime._memory_patch_admission)
                self.assertIsNone(runtime._cpl_service)
                self.assertIsNone(runtime._nonzero_service)
                self.assertEqual(
                    403,
                    runtime.memory_patch_operator_request(
                        "slot-create", {"operation_key": "x"}
                    )[0],
                )
                connect.assert_not_called()
                manager.assert_not_called()
                self.assertEqual([], list(Path(directory).rglob("*memory_patch*")))
            finally:
                runtime.close()

    def test_enabled_module_without_approved_owner_denies_before_composition(self):
        import tempfile
        from pathlib import Path

        from runtime.main import AgentRuntime
        from runtime.memory_patch.contract import MemoryPatchConfig

        with tempfile.TemporaryDirectory() as directory:
            runtime = AgentRuntime(
                Mock(),
                "fixture",
                Path(directory),
                memory_patch_config=MemoryPatchConfig(True),
            )
            try:
                status, value = runtime.memory_patch_operator_request(
                    "slot-create", {"operation_key": "x"}
                )
                self.assertEqual(403, status)
                self.assertFalse(value["ok"])
                self.assertIsNone(runtime._memory_patch_service)
            finally:
                runtime.close()

    def test_default_service_has_no_implicit_fake_or_database(self):
        from runtime.memory_patch.contract import MemoryPatchConfig
        from runtime.memory_patch.service import MemoryPatchService

        core = make_admission()
        with patch("socket.create_connection") as connect:
            service = MemoryPatchService(
                core, config=MemoryPatchConfig(True, core._assignment)
            )
            status, result = service.request(
                core.local_operator(Capability.MANAGE),
                "slot-create",
                {"operation_key": "x"},
            )
            self.assertEqual(503, status)
            self.assertEqual("BACKEND_UNCONFIGURED", result["error"]["code"])
            connect.assert_not_called()
            service.close()

    def test_configuration_is_immutable_and_no_json_identity_configuration(self):
        from dataclasses import FrozenInstanceError

        from runtime.memory_patch.contract import MemoryPatchConfig, snapshot_config

        config = MemoryPatchConfig(True, make_admission()._assignment)
        with self.assertRaises(FrozenInstanceError):
            config.enabled = False
        for value in ({"enabled": True, "operator": True}, True, "enabled"):
            with self.assertRaises(AdmissionError):
                snapshot_config(value)

    def test_unconfigured_provider_never_resolves_ambient_keys(self):
        from test_memory_patch_correction import CorrectionFixture

        from runtime.memory_patch.provider_adapter import NativeProviderAdapter

        fx = CorrectionFixture()
        packet, _ = fx.integrity.build(
            fx.principal, fx.draft("The reviewed policy applies."), fx.bundle
        )
        manager = Mock()
        with patch.dict(
            "os.environ",
            {"OPENAI_API_KEY": "synthetic-unused", "MEMORY_PATCH_LIVE": "true"},
        ):
            with self.assertRaises(MemoryPatchError):
                NativeProviderAdapter(fx.core, manager).draft(
                    fx.principal, packet, fx.bundle, attempt=1
                )
        self.assertEqual([], manager.mock_calls)
