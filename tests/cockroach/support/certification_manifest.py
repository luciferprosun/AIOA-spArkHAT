"""Explicit disposable certification inputs; import never resolves credentials."""

from __future__ import annotations

import hashlib
import json
import secrets
from pathlib import Path

from runtime.core_admission import (
    Capability,
    CoreAdmission,
    LocalOwnerAssignment,
    OwnerScope,
)
from runtime.memory_patch.adapters.cockroach.migration_controller import (
    NativeMigrationController,
    load_assets,
)
from runtime.memory_patch.adapters.cockroach.pool import (
    CoreDatabaseHandle,
    CoreOpenedConnection,
    CorePurposePool,
    DatabasePurpose,
)
from runtime.memory_patch.adapters.cockroach.transaction import (
    CockroachTransactionFactory,
    CoreContextBroker,
)
from runtime.memory_patch.persistence.migration_contract import (
    JuryDenylist,
    TargetAllowlist,
    TargetIdentity,
)

VERSION = "v26.2.5"
DRIVER = "3.3.5"
_configured = None
ARCHIVE_SHA256 = "067bd264ff1d39483049f5c75b26f704a10038d8d11fca53b5b8a48894c92d5d"
BINARY_SHA256 = "5ad89c804abb3bf5afa9c073faecb3710a1c4f34a870f08cdef889c1c91d314b"


def make_core(
    *,
    tenant="fixture-tenant-a",
    owner="fixture-owner-a",
    space=None,
    clock=None,
    hat_ids=frozenset({"test-hat"}),
):
    scope = OwnerScope(
        tenant, owner, space or "space-" + secrets.token_hex(8), "fixture-slot"
    )
    assignment = LocalOwnerAssignment(
        scope,
        frozenset(Capability),
        frozenset(hat_ids),
        frozenset({"test-model"}),
        operator_approved=True,
    )
    return CoreAdmission(assignment, clock=clock)


class CertificationInputs:
    def __init__(self, private_dir, results_dir):
        self.private = Path(private_dir).resolve()
        self.results = Path(results_dir).resolve()
        config = json.loads((self.private / "config.json").read_text())
        assert config["mode"] == "C5_DISPOSABLE"
        assert config["disposable_ownership_confirmed"] is True
        assert (self.private / "READY").exists() and not (
            self.private / "STOP"
        ).exists()
        data = dict(config["target"])
        data["account_ids"] = tuple(data["account_ids"])
        data["resource_arns"] = tuple(data["resource_arns"])
        self.target = TargetIdentity(**data)
        self.allowlist = TargetAllowlist(frozenset({self.target.fingerprint}))
        self.denylist = JuryDenylist.from_manifest(
            json.loads((self.private / "jury-canaries.json").read_text())
        )
        self.prefix = config["role_prefix"]
        self.certs = Path(config["certs_dir"]).resolve()
        assert self.certs.is_relative_to(self.private)
        self.calls = []
        self.check()

    def verify_binary(self):
        config = json.loads((self.private / "config.json").read_text())
        binary = Path(config["binary"])
        with binary.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        assert actual == BINARY_SHA256
        return {
            "binary_sha256": actual,
            "archive_sha256": ARCHIVE_SHA256,
            "version": VERSION,
        }

    def check(self):
        self.allowlist.require_allowed(self.target)
        self.denylist.require_clear(self.target)
        assert (
            hashlib.sha256((self.certs / "ca.crt").read_bytes()).hexdigest()
            == self.target.certificate_fingerprint
        )

    def connect(self, role):
        self.check()
        assert role == "root" or role in {
            self.prefix + "_" + s
            for s in (*load_assets()[0]["role_suffixes"], "migrator")
        }
        import psycopg

        assert psycopg.__version__ == DRIVER
        self.calls.append(
            {
                "role_suffix": role.removeprefix(self.prefix + "_"),
                "target_fingerprint": self.target.fingerprint,
            }
        )
        return psycopg.connect(
            host=self.target.address,
            port=self.target.port,
            dbname=self.target.database,
            user=role,
            sslmode="verify-full",
            sslrootcert=str(self.certs / "ca.crt"),
            sslcert=str(self.certs / ("client." + role + ".crt")),
            sslkey=str(self.certs / ("client." + role + ".key")),
            connect_timeout=5,
            autocommit=True,
        )

    def handle(self, suffix, purpose):
        role = self.prefix + "_" + suffix

        def opened(target, requested_role):
            assert target == self.target and requested_role == role
            return CoreOpenedConnection(
                self.connect(role),
                target.fingerprint,
                target.certificate_fingerprint,
                True,
            )

        return CoreDatabaseHandle(role, purpose, opened)

    def controller(self, core):
        return NativeMigrationController(
            core,
            self.allowlist,
            self.denylist,
            self.handle("migrator", DatabasePurpose.MIGRATOR),
        )

    def factory(
        self,
        core,
        *,
        evidence_role="publication",
        read_role="app",
        schema_profile="base",
    ):
        mapping = {
            Capability.READ: (
                read_role,
                DatabasePurpose.APPLICATION
                if read_role == "app"
                else DatabasePurpose.AUDIT,
            ),
            Capability.COMMIT: ("commit", DatabasePurpose.COMMIT),
            Capability.ACTIVATE: ("commit", DatabasePurpose.COMMIT),
            Capability.REVIEW: ("reviewer", DatabasePurpose.REVIEW),
            Capability.EVIDENCE_CAPTURE: (
                evidence_role,
                DatabasePurpose.PUBLICATION
                if evidence_role == "publication"
                else DatabasePurpose.INGESTION,
            ),
        }
        for cap in (
            Capability.CANDIDATE,
            Capability.PROPOSE,
            Capability.VALIDATE,
            Capability.OWNER_APPROVAL,
            Capability.MANAGE,
        ):
            mapping[cap] = ("app", DatabasePurpose.APPLICATION)
        handles = tuple((cap, self.handle(*value)) for cap, value in mapping.items())
        pool = CorePurposePool(
            core,
            self.target,
            self.allowlist,
            self.denylist,
            handles,
            approved_manifest_digest=load_assets(schema_profile)[2],
            schema_profile=schema_profile,
        )
        return CockroachTransactionFactory(
            pool,
            CoreContextBroker(
                core,
                pool,
                self.handle("broker", DatabasePurpose.CONTEXT),
            ),
        )

    def save(self, name, value):
        assert name.startswith("C5_") and name.endswith(".json") and "/" not in name
        (self.results / name).write_text(
            json.dumps(value, indent=2, default=str) + "\n"
        )


def configure(private_dir, results_dir):
    global _configured
    _configured = CertificationInputs(private_dir, results_dir)
    return _configured


def inputs():
    if _configured is None:
        raise RuntimeError("Explicit disposable certification inputs required")
    return _configured


def memory_fixture(*, tenant="fixture-tenant-a", owner="fixture-owner-a"):
    from unittest.mock import patch

    from test_memory_patch_lifecycle import MemoryFixture
    from test_memory_patch_persistence_ports import NOW

    from runtime.memory_patch.persistence.ports import TransactionContext

    core = make_core(tenant=tenant, owner=owner, clock=lambda: NOW)
    factory = inputs().factory(core)
    with patch("test_memory_patch_retrieval.make_admission", return_value=core):
        fixture = MemoryFixture(factory=factory)

    def rows(kind):
        principal = core.local_operator(Capability.READ)
        return fixture.runner.run(
            TransactionContext(principal, Capability.READ),
            lambda tx: tx.scan(kind, limit=1024),
        )

    fixture.rows = rows
    original_close = fixture.close

    def close():
        factory.close()
        original_close()

    fixture.close = close
    return fixture
