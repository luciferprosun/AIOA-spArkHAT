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


def load_assets(schema_profile="base"):
    root = importlib.resources.files("runtime.memory_patch").joinpath("sql")
    try:
        if schema_profile not in {"base", "learning-v1"}:
            raise ValueError("schema profile")
        filename = "manifest.json" if schema_profile == "base" else "manifest-learning-v1.json"
        manifest = json.loads(root.joinpath(filename).read_text())
        if (
            manifest["schema"] != "native-memory-patch-cockroach-manifest-v1"
            or manifest["compatibility_version"] != "v26.2.5"
            or manifest["native_schema"] != "aioa_memory_patch"
            or [u["ordinal"] for u in manifest["units"]]
            != list(range(1, 19 if schema_profile == "base" else 20))
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
        "schema_permissions": _rows(
            connection,
            "SELECT r.rolname,pg_catalog.has_schema_privilege(r.oid,n.oid,'USAGE'),"
            "pg_catalog.has_schema_privilege(r.oid,n.oid,'CREATE') "
            "FROM pg_catalog.pg_roles r JOIN pg_catalog.pg_namespace n ON n.nspname=%s "
            "WHERE r.rolname::STRING=ANY(%s::STRING[]) ORDER BY r.rolname",
            (schema, names),
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
        "constraint_definitions": _rows(
            connection,
            "SELECT t.relname,c.conname,c.contype,pg_catalog.pg_get_constraintdef(c.oid) "
            "FROM pg_catalog.pg_constraint c JOIN pg_catalog.pg_class t ON t.oid=c.conrelid "
            "JOIN pg_catalog.pg_namespace n ON n.oid=c.connamespace WHERE n.nspname=%s "
            "ORDER BY t.relname,c.conname",
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
            "SELECT p.proname,p.prosecdef,pg_catalog.pg_get_functiondef(p.oid),r.rolname "
            "FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n "
            "ON n.oid=p.pronamespace JOIN pg_catalog.pg_roles r ON r.oid=p.proowner "
            "WHERE n.nspname=%s ORDER BY p.proname,p.oid",
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
        "triggers": _rows(
            connection,
            "SELECT trigger_name,event_manipulation,event_object_table,action_statement,action_timing "
            "FROM information_schema.triggers WHERE trigger_schema=%s ORDER BY trigger_name,event_manipulation",
            (schema,),
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
    function_names = [row[0] for row in result["functions"]]
    if any(not re.fullmatch(r"[a-z][a-z_]{1,63}", name) for name in function_names):
        raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
    # pg_proc.proacl and has_function_privilege do not expose the actual
    # v26.2.5 UDF grants reliably. SHOW GRANTS is the supported object view.
    result["function_grants"] = (
        _rows(
            connection,
            "SELECT routine_signature,grantee,privilege_type,is_grantable FROM [SHOW GRANTS ON FUNCTION "
            + ",".join(schema + "." + name for name in function_names)
            + "] ORDER BY routine_signature,grantee,privilege_type",
        )
        if function_names
        else []
    )
    return result


def read_applied(connection, state):
    if not state["schema"]:
        return ()
    if "schema_migrations" not in {row[0] for row in state["tables"]}:
        raise MemoryPatchError(ErrorCode.RECOVERY_REQUIRED)
    rows = _rows(
        connection,
        "SELECT ordinal,name,checksum,manifest_digest "
        "FROM aioa_memory_patch.schema_migrations WHERE state='APPLIED' ORDER BY ordinal",
    )
    return tuple(tuple(row) for row in rows)


def read_pending(connection, state, manifest, digest, applied):
    if not state["schema"]:
        return ()
    rows = _rows(
        connection,
        "SELECT ordinal,name,checksum,manifest_digest,completed_statements,catalog_fingerprint "
        "FROM aioa_memory_patch.schema_migrations WHERE state='APPLYING' ORDER BY ordinal",
    )
    if not rows:
        return ()
    if len(rows) != 1 or len(applied) >= len(manifest["units"]):
        raise MemoryPatchError(ErrorCode.RECOVERY_REQUIRED)
    row = rows[0]
    expected = manifest["units"][len(applied)]
    if (
        row[:4] != [expected["ordinal"], expected["path"], expected["sha256"], digest]
        or not 0 <= row[4] <= expected["statement_count"]
        or row[5] != canonical_sha256(state)
    ):
        # An acknowledgement gap or unexplained catalog change is not replayed.
        raise MemoryPatchError(ErrorCode.RECOVERY_REQUIRED)
    return tuple(row)


def validate_prefix(applied, manifest, digest):
    expected = tuple(
        (u["ordinal"], u["path"], u["sha256"], digest)
        for u in manifest["units"][: len(applied)]
    )
    if len(applied) > len(manifest["units"]) or applied != expected:
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
    schema_privileges = {row[0]: row[1:] for row in state["schema_permissions"]}
    for suffix in manifest["role_suffixes"]:
        name = prefix + "_" + suffix
        row = roles.get(name)
        if not row or row[1] or row[2] or row[3] or row[5] or row[6]:
            raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
        if row[4] != (suffix not in {"schema_owner", "security_owner"}):
            raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
        if schema_privileges.get(name) != [True, False]:
            raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
    actual_policies = {row[1] for row in state["policies"]}
    expected_policies = set()
    for name in manifest["scoped_tables"]:
        expected_policies.update({name + "_read", name + "_insert"})
        if name not in manifest["native_immutable_tables"]:
            expected_policies.add(name + "_update")
    if actual_policies != expected_policies:
        raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
    definitions = state["constraint_definitions"]
    for table in manifest["scoped_tables"]:
        primary = [r[3] for r in definitions if r[0] == table and r[2] == "p"]
        if len(primary) != 1 or not primary[0].startswith(
            "PRIMARY KEY (tenant_id ASC, owner_id ASC, space_id ASC, slot_id ASC,"
        ):
            raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
    for table, _, kind, definition in definitions:
        if (
            table in manifest["scoped_tables"]
            and kind == "f"
            and not definition.startswith(
                "FOREIGN KEY (tenant_id, owner_id, space_id, slot_id,"
            )
        ):
            raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
    functions = {row[0]: row for row in state["functions"]}
    expected_functions = {
        "mint_context_ticket",
        "set_request_context",
        "clear_request_context",
        "scope_allows",
        "hat_allows",
        "review_patch_visible",
        "guard_patch",
        "guard_review",
    }
    if set(functions) != expected_functions:
        raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
    ordinary = set(manifest["read_role_tables"])
    for name, row in functions.items():
        owner_suffix = (
            "schema_owner"
            if name in {"review_patch_visible", "guard_patch", "guard_review"}
            else "security_owner"
        )
        # v26.2.5 reports pg_proc.prosecdef=False even for SECURITY DEFINER
        # functions. The reconstructed DDL exposes the actual security mode.
        header, delimiter, _ = row[2].partition("AS $$")
        security = re.findall(
            r"(?m)^[ \t]*SECURITY (DEFINER|INVOKER)[ \t]*$", header
        )
        expected_security = (
            "INVOKER" if name in {"guard_patch", "guard_review"} else "DEFINER"
        )
        if (
            not delimiter
            or security != [expected_security]
            or row[3] != prefix + "_" + owner_suffix
        ):
            raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
        allowed = {"broker"} if name == "mint_context_ticket" else set(ordinary)
        if name in {"scope_allows", "hat_allows"}:
            allowed.add("schema_owner")
        actual = set()
        for signature, grantee, privilege, grantable in state["function_grants"]:
            if signature.split("(", 1)[0] != name:
                continue
            if grantee in {"root", "admin", row[3]} and privilege == "ALL":
                continue
            if (
                not grantee.startswith(prefix + "_")
                or privilege != "EXECUTE"
                or grantable
            ):
                raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
            actual.add(grantee.removeprefix(prefix + "_"))
        if actual != allowed:
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
    if {(row[0], row[1], row[2], row[4]) for row in state["triggers"]} != {
        ("patch_integrity", "INSERT", "patches", "BEFORE"),
        ("patch_integrity", "UPDATE", "patches", "BEFORE"),
        ("review_integrity", "INSERT", "reviews", "BEFORE"),
        ("review_integrity", "UPDATE", "reviews", "BEFORE"),
    }:
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
    pending: tuple = ()
    _seal: bytes = field(default=b"", repr=False)


class NativeMigrationController:
    def __init__(self, core, allowlist, denylist, handle, *, clock=None, schema_profile="base"):
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
        load_assets(schema_profile)
        self.schema_profile = schema_profile
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
        manifest, _, digest = load_assets(self.schema_profile)
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
            pending = read_pending(connection, state, manifest, digest, applied)
            snapshot = CatalogSnapshot(
                target.fingerprint,
                canonical_sha256(state),
                applied,
                digest,
                principal.actor_session_id,
                principal.scope.binding(),
                self.clock() + timedelta(minutes=5),
                pending=pending,
            )
            return replace(snapshot, _seal=self._sign(snapshot))
        finally:
            connection.close()

    def plan(self, principal, target, snapshot):
        self._snapshot(principal, target, snapshot)
        manifest, _, digest = load_assets(self.schema_profile)
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
            or snapshot.manifest_digest != load_assets(self.schema_profile)[2]
        ):
            raise MemoryPatchError(ErrorCode.MIGRATION_DENIED)

    def execute(self, principal, plan, authorization, snapshot, *, observer=None):
        self._snapshot(principal, plan.target, snapshot)
        manifest, statements, digest = load_assets(self.schema_profile)
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
            with connection.cursor() as cursor:
                # v26.2 defaults this setting to on. Never silently commit a
                # migration phase when its first DDL statement is encountered.
                cursor.execute("SET autocommit_before_ddl = off")
                cursor.execute("SHOW autocommit_before_ddl")
                if cursor.fetchone()[0].lower() != "off":
                    raise MemoryPatchError(ErrorCode.MIGRATION_DENIED)
            state = catalog(connection, prefix)
            if canonical_sha256(state) != snapshot.catalog_fingerprint:
                raise MemoryPatchError(ErrorCode.MIGRATION_DENIED)
            applied = read_applied(connection, state)
            validate_prefix(applied, manifest, digest)
            if applied != snapshot.applied:
                raise MemoryPatchError(ErrorCode.MIGRATION_DENIED)
            pending = read_pending(connection, state, manifest, digest, applied)
            if pending != snapshot.pending:
                raise MemoryPatchError(ErrorCode.MIGRATION_DENIED)
            if len(applied) == len(manifest["units"]):
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
            role_phases = enumerate(manifest["role_suffixes"], 1) if not applied else ()
            if applied:
                existing_roles = {row[0]: row for row in state["roles"]}
                for suffix in manifest["role_suffixes"]:
                    flags = existing_roles.get(prefix + "_" + suffix)
                    if flags is None or flags[1:] != [
                        False,
                        False,
                        False,
                        suffix not in {"schema_owner", "security_owner"},
                        False,
                        False,
                    ]:
                        raise MemoryPatchError(ErrorCode.RECOVERY_REQUIRED)
            for ordinal, suffix in role_phases:
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
                if ordinal == 1:
                    # Only the small metadata bootstrap uses a transaction.
                    # Its rollback is independently exercised by certification.
                    try:
                        with connection.cursor() as cursor:
                            cursor.execute("BEGIN ISOLATION LEVEL SERIALIZABLE")
                            for statement in statements[ordinal]:
                                cursor.execute(
                                    statement.replace("__ROLE_PREFIX__", prefix)
                                )
                                if connection.info.transaction_status.name != "INTRANS":
                                    raise MemoryPatchError(ErrorCode.RECOVERY_REQUIRED)
                            cursor.execute(
                                "INSERT INTO aioa_memory_patch.schema_migrations(ordinal,name,checksum,manifest_digest,state,completed_statements,catalog_fingerprint) VALUES(%s,%s,%s,%s,'APPLIED',%s,%s)",
                                (
                                    ordinal,
                                    row["path"],
                                    row["sha256"],
                                    digest,
                                    len(statements[ordinal]),
                                    canonical_sha256(catalog(connection, prefix)),
                                ),
                            )
                            observe("unit_before_commit", ordinal)
                        connection.commit()
                    except BaseException:
                        connection.rollback()
                        raise
                    observe("unit_after_commit", ordinal)
                    state = catalog(connection, prefix)
                    continue
                current = state
                completed_prefix = read_applied(connection, current)
                pending = read_pending(
                    connection, current, manifest, digest, completed_prefix
                )
                start = pending[4] if pending else 0
                if not pending:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "INSERT INTO aioa_memory_patch.schema_migrations(ordinal,name,checksum,manifest_digest,state,completed_statements,catalog_fingerprint) VALUES(%s,%s,%s,%s,'APPLYING',0,%s)",
                            (
                                ordinal,
                                row["path"],
                                row["sha256"],
                                digest,
                                canonical_sha256(current),
                            ),
                        )
                for index, statement in enumerate(
                    statements[ordinal][start:], start + 1
                ):
                    self.core.require(principal, Capability.MIGRATE)
                    observe("statement_before", ordinal * 10000 + index)
                    with connection.cursor() as cursor:
                        cursor.execute(
                            statement.replace("__ROLE_PREFIX__", prefix), prepare=False
                        )
                    if connection.info.transaction_status.name != "IDLE":
                        raise MemoryPatchError(ErrorCode.RECOVERY_REQUIRED)
                    state = catalog(connection, prefix)
                    after = canonical_sha256(state)
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "UPDATE aioa_memory_patch.schema_migrations SET completed_statements=%s,catalog_fingerprint=%s WHERE ordinal=%s AND state='APPLYING' AND completed_statements=%s",
                            (index, after, ordinal, index - 1),
                        )
                        if cursor.rowcount != 1:
                            raise MemoryPatchError(ErrorCode.RECOVERY_REQUIRED)
                    observe("statement_after", ordinal * 10000 + index)
                # This checkpoint certifies acknowledged DDL, not DDL rollback.
                observe("unit_before_commit", ordinal)
                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE aioa_memory_patch.schema_migrations SET state='APPLIED' WHERE ordinal=%s AND state='APPLYING' AND completed_statements=%s",
                        (ordinal, row["statement_count"]),
                    )
                    if cursor.rowcount != 1:
                        raise MemoryPatchError(ErrorCode.RECOVERY_REQUIRED)
                observe("unit_after_commit", ordinal)
            final = catalog(connection, prefix)
            fingerprint = validate_catalog(final, manifest, prefix)
            completed = read_applied(connection, final)
            validate_prefix(completed, manifest, digest)
            if len(completed) != len(manifest["units"]):
                raise MemoryPatchError(ErrorCode.RECOVERY_REQUIRED)
            existing = _rows(
                connection,
                "SELECT manifest_digest,catalog_fingerprint,state FROM aioa_memory_patch.schema_certificate WHERE singleton=true",
            )
            if existing:
                if existing != [[digest, fingerprint, "READY"]]:
                    raise MemoryPatchError(ErrorCode.RECOVERY_REQUIRED)
            else:
                observe("certificate_before", len(manifest["units"]))
                with connection.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO aioa_memory_patch.schema_certificate VALUES(true,%s,%s,'READY')",
                        (digest, fingerprint),
                    )
                observe("certificate_after", len(manifest["units"]))
            return {
                "state": "READY",
                "replayed": len(applied) == len(manifest["units"]) and bool(existing),
                "applied_this_run": len(manifest["units"]) - len(applied),
                "manifest_digest": digest,
                "catalog_fingerprint": fingerprint,
                "progress": tuple(progress),
            }
        finally:
            connection.close()

    def close(self):
        self._closed = True
        self._key = b""
