"""Explicit Core-admitted native migrations; no ambient startup execution."""

from __future__ import annotations

import hashlib
import hmac
import importlib.resources
import json
import re
import secrets
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone

from runtime.core_admission import Capability
from runtime.memory_patch.adapters.cockroach.pool import (
    CoreDatabaseHandle,
    DatabasePurpose,
    open_admitted_handle,
)
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.memory_patch.errors import ErrorCode, MemoryPatchError
from runtime.memory_patch.persistence.migration_contract import (
    MigrationAdmission,
    MigrationPlan,
    MigrationUnit,
)


def load_assets():
    root = importlib.resources.files("runtime.memory_patch").joinpath("sql")
    try:
        manifest = json.loads(root.joinpath("manifest.json").read_text())
        if (
            manifest["schema"] != "native-memory-patch-cockroach-manifest-v1"
            or manifest["compatibility_version"] != "v26.2.5"
            or manifest["native_schema"] != "aioa_memory_patch"
            or [u["ordinal"] for u in manifest["units"]] != list(range(1, 19))
        ):
            raise ValueError("manifest")
        statements = {}
        for row in manifest["units"]:
            MigrationUnit(row["ordinal"], row["path"], row["sha256"])
            raw = root.joinpath(row["path"]).read_bytes()
            if hashlib.sha256(raw).hexdigest() != row["sha256"]:
                raise ValueError("migration checksum")
            parts = tuple(raw.decode("utf-8").split("\n-- C5_STATEMENT\n"))
            if len(parts) != row["statement_count"] or not all(
                p.strip() for p in parts
            ):
                raise ValueError("migration phase framing")
            statements[row["ordinal"]] = parts
        return manifest, statements, canonical_sha256(manifest)
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise MemoryPatchError(ErrorCode.MIGRATION_DENIED) from error


def role_prefix(target):
    if not target.application_role.endswith("_app"):
        raise MemoryPatchError(ErrorCode.MIGRATION_DENIED)
    prefix = target.application_role[:-4]
    if (
        not re.fullmatch(r"[a-z][a-z0-9_]{0,42}", prefix)
        or target.migrator_role != prefix + "_migrator"
    ):
        raise MemoryPatchError(ErrorCode.MIGRATION_DENIED)
    return prefix


def _rows(connection, query, args=()):
    with connection.cursor() as cursor:
        cursor.execute(query, args)
        return [list(row) for row in cursor.fetchall()]


def catalog(connection, prefix):
    """Supported catalog interfaces; no crdb_internal/system bypass flag."""
    schema = "aioa_memory_patch"
    names = [prefix + "_" + suffix for suffix in load_assets()[0]["role_suffixes"]]
    names.append(prefix + "_migrator")
    result = {
        "schema": _rows(
            connection,
            "SELECT schema_name FROM information_schema.schemata WHERE schema_name=%s",
            (schema,),
        ),
        "columns": _rows(
            connection,
            "SELECT table_name,column_name,data_type,is_nullable,column_default,"
            "generation_expression FROM information_schema.columns "
            "WHERE table_schema=%s ORDER BY table_name,ordinal_position",
            (schema,),
        ),
        "tables": _rows(
            connection,
            "SELECT c.relname,c.relrowsecurity,c.relforcerowsecurity,r.rolname "
            "FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n "
            "ON n.oid=c.relnamespace JOIN pg_catalog.pg_roles r ON r.oid=c.relowner "
            "WHERE n.nspname=%s AND c.relkind='r' ORDER BY c.relname",
            (schema,),
        ),
        "constraints": _rows(
            connection,
            "SELECT tc.table_name,tc.constraint_name,tc.constraint_type "
            "FROM information_schema.table_constraints tc WHERE tc.constraint_schema=%s "
            "ORDER BY tc.table_name,tc.constraint_name",
            (schema,),
        ),
        "policies": _rows(
            connection,
            "SELECT tablename,policyname,permissive,roles::STRING,cmd,qual,with_check "
            "FROM pg_catalog.pg_policies WHERE schemaname=%s ORDER BY tablename,policyname",
            (schema,),
        ),
        "functions": _rows(
            connection,
            "SELECT p.proname,p.prosecdef,pg_catalog.pg_get_functiondef(p.oid) "
            "FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n "
            "ON n.oid=p.pronamespace WHERE n.nspname=%s ORDER BY p.proname,p.oid",
            (schema,),
        ),
        "indexes": _rows(
            connection,
            "SELECT tablename,indexname,indexdef FROM pg_catalog.pg_indexes "
            "WHERE schemaname=%s ORDER BY tablename,indexname",
            (schema,),
        ),
        "grants": _rows(
            connection,
            "SELECT table_name,grantee,privilege_type,is_grantable "
            "FROM information_schema.table_privileges WHERE table_schema=%s "
            "ORDER BY table_name,grantee,privilege_type",
            (schema,),
        ),
        "roles": _rows(
            connection,
            "SELECT rolname,rolsuper,rolcreaterole,rolcreatedb,rolcanlogin,rolbypassrls,"
            "pg_catalog.pg_has_role(rolname,'admin','MEMBER') "
            "FROM pg_catalog.pg_roles WHERE rolname::STRING=ANY(%s::STRING[]) "
            "ORDER BY rolname",
            (names,),
        ),
        "memberships": _rows(
            connection,
            "SELECT parent.rolname,member.rolname,m.admin_option "
            "FROM pg_catalog.pg_auth_members m JOIN pg_catalog.pg_roles parent "
            "ON parent.oid=m.roleid JOIN pg_catalog.pg_roles member ON member.oid=m.member "
            "WHERE parent.rolname::STRING=ANY(%s::STRING[]) "
            "OR member.rolname::STRING=ANY(%s::STRING[]) "
            "ORDER BY parent.rolname,member.rolname",
            (names, names),
        ),
    }
    return result


def read_applied(connection, state):
    if not state["schema"]:
        return ()
    if "schema_migrations" not in {row[0] for row in state["tables"]}:
        raise MemoryPatchError(ErrorCode.RECOVERY_REQUIRED)
    rows = _rows(
        connection,
        "SELECT ordinal,name,checksum,manifest_digest "
        "FROM aioa_memory_patch.schema_migrations ORDER BY ordinal",
    )
    return tuple(tuple(row) for row in rows)


def validate_prefix(applied, manifest, digest):
    expected = tuple(
        (u["ordinal"], u["path"], u["sha256"], digest)
        for u in manifest["units"][: len(applied)]
    )
    if len(applied) > 18 or applied != expected:
        raise MemoryPatchError(ErrorCode.MIGRATION_DENIED)


def validate_catalog(state, manifest, prefix):
    expected = set(manifest["scoped_tables"]) | set(manifest["unscoped_exceptions"])
    if {row[0] for row in state["tables"]} != expected:
        raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
    for name, enabled, forced, owner in state["tables"]:
        scoped = name in manifest["scoped_tables"]
        if scoped and (not enabled or not forced or owner != prefix + "_schema_owner"):
            raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
        if not scoped and owner != prefix + "_security_owner":
            raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
    roles = {row[0]: row for row in state["roles"]}
    for suffix in manifest["role_suffixes"]:
        name = prefix + "_" + suffix
        row = roles.get(name)
        if not row or row[1] or row[2] or row[3] or row[5] or row[6]:
            raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
        if row[4] != (suffix not in {"schema_owner", "security_owner"}):
            raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
    actual_policies = {row[1] for row in state["policies"]}
    expected_policies = set()
    for name in manifest["scoped_tables"]:
        expected_policies.update({name + "_read", name + "_insert"})
        if name not in manifest["native_immutable_tables"]:
            expected_policies.add(name + "_update")
    if actual_policies != expected_policies:
        raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
    for row in state["grants"]:
        name, grantee, privilege, _ = row
        if grantee == "public" or (
            grantee.startswith(prefix + "_")
            and grantee
            not in {
                prefix + "_schema_owner",
                prefix + "_security_owner",
                prefix + "_migrator",
            }
            and privilege in {"DELETE", "CREATE", "DROP", "TRIGGER"}
        ):
            raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
    if not any(row[1] == "scoped_vector_l2_idx" for row in state["indexes"]):
        raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
    return canonical_sha256(state)


@dataclass(frozen=True, slots=True, repr=False)
class CatalogSnapshot:
    target_fingerprint: str
    catalog_fingerprint: str
    applied: tuple
    manifest_digest: str
    actor_session_id: str
    scope_binding: tuple
    expires_at: datetime
    _seal: bytes = field(default=b"", repr=False)


class NativeMigrationController:
    def __init__(self, core, allowlist, denylist, handle, *, clock=None):
        if (
            type(handle) is not CoreDatabaseHandle
            or handle.purpose is not DatabasePurpose.MIGRATOR
        ):
            raise MemoryPatchError(ErrorCode.MIGRATION_DENIED)
        self.core, self.allowlist, self.denylist, self.handle = (
            core,
            allowlist,
            denylist,
            handle,
        )
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.admission = MigrationAdmission(core, allowlist, denylist, clock=self.clock)
        self._key = secrets.token_bytes(32)
        self._closed = False

    def _sign(self, value):
        return hmac.digest(
            self._key,
            canonical_sha256(value, exclude_fields=("_seal",)).encode(),
            "sha256",
        )

    def _target(self, principal, target, confirmation):
        if self._closed:
            raise MemoryPatchError(ErrorCode.MODULE_CLOSED)
        self.core.require(principal, Capability.MIGRATE)
        if confirmation is not True or self.handle.role != target.migrator_role:
            raise MemoryPatchError(ErrorCode.MIGRATION_DENIED)
        role_prefix(target)
        self.admission.check_target(target)

    def inspect(self, principal, target, *, disposable_ownership_confirmed):
        """Separate explicit read-only operator action, never ordinary startup."""
        self._target(principal, target, disposable_ownership_confirmed)
        manifest, _, digest = load_assets()
        connection = open_admitted_handle(
            self.handle, target, self.allowlist, self.denylist
        )
        try:
            version = _rows(connection, "SELECT version()")[0][0]
            if not re.search(r"\bv26\.2\.5(?:\s|$)", version):
                raise MemoryPatchError(ErrorCode.TARGET_DENIED)
            state = catalog(connection, role_prefix(target))
            applied = read_applied(connection, state)
            validate_prefix(applied, manifest, digest)
            snapshot = CatalogSnapshot(
                target.fingerprint,
                canonical_sha256(state),
                applied,
                digest,
                principal.actor_session_id,
                principal.scope.binding(),
                self.clock() + timedelta(minutes=5),
            )
            return replace(snapshot, _seal=self._sign(snapshot))
        finally:
            connection.close()

    def plan(self, principal, target, snapshot):
        self._snapshot(principal, target, snapshot)
        manifest, _, digest = load_assets()
        return MigrationPlan(
            "plan_" + secrets.token_hex(16),
            target,
            "Native disposable schema",
            snapshot.catalog_fingerprint,
            digest,
            tuple(
                MigrationUnit(u["ordinal"], u["path"], u["sha256"])
                for u in manifest["units"]
            ),
        )

    def _snapshot(self, principal, target, snapshot):
        self._target(principal, target, True)
        if (
            type(snapshot) is not CatalogSnapshot
            or snapshot.target_fingerprint != target.fingerprint
            or snapshot.actor_session_id != principal.actor_session_id
            or snapshot.scope_binding != principal.scope.binding()
            or self.clock() >= snapshot.expires_at
            or not hmac.compare_digest(snapshot._seal, self._sign(snapshot))
            or snapshot.manifest_digest != load_assets()[2]
        ):
            raise MemoryPatchError(ErrorCode.MIGRATION_DENIED)

    def execute(self, principal, plan, authorization, snapshot, *, observer=None):
        self._snapshot(principal, plan.target, snapshot)
        manifest, statements, digest = load_assets()
        expected_units = tuple(
            MigrationUnit(u["ordinal"], u["path"], u["sha256"])
            for u in manifest["units"]
        )
        if plan.units != expected_units or plan.expected_schema_fingerprint != digest:
            raise MemoryPatchError(ErrorCode.MIGRATION_DENIED)
        self.admission.consume(
            principal,
            plan,
            authorization,
            observed_schema_fingerprint=snapshot.catalog_fingerprint,
        )
        connection = open_admitted_handle(
            self.handle, plan.target, self.allowlist, self.denylist
        )
        prefix = role_prefix(plan.target)
        progress = []

        def observe(stage, ordinal):
            progress.append({"stage": stage, "ordinal": ordinal})
            if observer is not None:
                observer(stage, ordinal)

        try:
            state = catalog(connection, prefix)
            if canonical_sha256(state) != snapshot.catalog_fingerprint:
                raise MemoryPatchError(ErrorCode.MIGRATION_DENIED)
            applied = read_applied(connection, state)
            validate_prefix(applied, manifest, digest)
            if applied != snapshot.applied:
                raise MemoryPatchError(ErrorCode.MIGRATION_DENIED)
            if len(applied) == 18:
                fingerprint = validate_catalog(state, manifest, prefix)
                certificate = _rows(
                    connection,
                    "SELECT manifest_digest,catalog_fingerprint,state FROM aioa_memory_patch.schema_certificate WHERE singleton=true",
                )
                if certificate:
                    if certificate != [[digest, fingerprint, "READY"]]:
                        raise MemoryPatchError(ErrorCode.RECOVERY_REQUIRED)
                    return {
                        "state": "READY",
                        "replayed": True,
                        "applied_this_run": 0,
                        "manifest_digest": digest,
                        "catalog_fingerprint": fingerprint,
                        "progress": (),
                    }
            # Roles are intentionally separate autocommit statements. Never
            # infer their rollback from a failed database transaction.
            for ordinal, suffix in enumerate(manifest["role_suffixes"], 1):
                role = prefix + "_" + suffix
                observe("role_before", ordinal)
                flags = _rows(
                    connection,
                    "SELECT rolcanlogin,rolsuper,rolcreaterole,rolcreatedb,rolbypassrls,pg_catalog.pg_has_role(rolname,'admin','MEMBER') FROM pg_catalog.pg_roles WHERE rolname=%s",
                    (role,),
                )
                login = suffix not in {"schema_owner", "security_owner"}
                if not flags:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "CREATE ROLE " + role + (" LOGIN" if login else " NOLOGIN")
                        )
                elif flags != [[login, False, False, False, False, False]]:
                    raise MemoryPatchError(ErrorCode.RECOVERY_REQUIRED)
                observe("role_created", ordinal)
                if suffix in {"schema_owner", "security_owner"}:
                    member = _rows(
                        connection,
                        "SELECT pg_catalog.pg_has_role(%s,%s,'MEMBER')",
                        (plan.target.migrator_role, role),
                    )[0][0]
                    if not member:
                        with connection.cursor() as cursor:
                            cursor.execute(
                                "GRANT " + role + " TO " + plan.target.migrator_role
                            )
                observe("role_after", ordinal)
            for row in manifest["units"][len(applied) :]:
                ordinal = row["ordinal"]
                self.core.require(principal, Capability.MIGRATE)
                observe("unit_before", ordinal)
                try:
                    with connection.cursor() as cursor:
                        cursor.execute("BEGIN ISOLATION LEVEL SERIALIZABLE")
                        for statement in statements[ordinal]:
                            cursor.execute(statement.replace("__ROLE_PREFIX__", prefix))
                        cursor.execute(
                            "INSERT INTO aioa_memory_patch.schema_migrations(ordinal,name,checksum,manifest_digest) VALUES(%s,%s,%s,%s)",
                            (ordinal, row["path"], row["sha256"], digest),
                        )
                        observe("unit_before_commit", ordinal)
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise
                observe("unit_after_commit", ordinal)
            final = catalog(connection, prefix)
            fingerprint = validate_catalog(final, manifest, prefix)
            completed = read_applied(connection, final)
            validate_prefix(completed, manifest, digest)
            if len(completed) != 18:
                raise MemoryPatchError(ErrorCode.RECOVERY_REQUIRED)
            existing = _rows(
                connection,
                "SELECT manifest_digest,catalog_fingerprint,state FROM aioa_memory_patch.schema_certificate WHERE singleton=true",
            )
            if existing:
                if existing != [[digest, fingerprint, "READY"]]:
                    raise MemoryPatchError(ErrorCode.RECOVERY_REQUIRED)
            else:
                observe("certificate_before", 18)
                with connection.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO aioa_memory_patch.schema_certificate VALUES(true,%s,%s,'READY')",
                        (digest, fingerprint),
                    )
                observe("certificate_after", 18)
            return {
                "state": "READY",
                "replayed": len(applied) == 18 and bool(existing),
                "applied_this_run": 18 - len(applied),
                "manifest_digest": digest,
                "catalog_fingerprint": fingerprint,
                "progress": tuple(progress),
            }
        finally:
            connection.close()

    def close(self):
        self._closed = True
        self._key = b""
