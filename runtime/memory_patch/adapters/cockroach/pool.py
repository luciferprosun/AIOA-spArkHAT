"""Lazy purpose handles injected by Core; no driver or credential discovery."""

from __future__ import annotations

import re
import socket
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from runtime.core_admission import Capability, CoreAdmission
from runtime.memory_patch.errors import ErrorCode, MemoryPatchError
from runtime.memory_patch.persistence.migration_contract import (
    JuryDenylist,
    TargetAllowlist,
    TargetIdentity,
)
from runtime.memory_patch.persistence.ports import TransactionContext


class DatabasePurpose(str, Enum):
    APPLICATION = "application"
    COMMIT = "commit"
    REVIEW = "review"
    PUBLICATION = "publication"
    INGESTION = "ingestion"
    AUDIT = "audit"
    CONTEXT = "context"
    MIGRATOR = "migrator"


@dataclass(frozen=True, slots=True, repr=False)
class CoreOpenedConnection:
    """Core's explicit TLS handle attests its verify-full CA binding.

    The adapter independently checks the real socket peer, TLS state and SQL
    identity. Core owns credential resolution; no public payload supplies this.
    """

    connection: Any = field(repr=False)
    target_fingerprint: str
    verified_ca_fingerprint: str
    verify_full: bool


@dataclass(frozen=True, slots=True, repr=False)
class CoreDatabaseHandle:
    role: str
    purpose: DatabasePurpose
    open_connection: Callable[[TargetIdentity, str], CoreOpenedConnection] = field(
        repr=False
    )

    def __post_init__(self):
        if (
            type(self.role) is not str
            or not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", self.role)
            or self.role in {"root", "admin", "node", "public"}
            or type(self.purpose) is not DatabasePurpose
            or not callable(self.open_connection)
        ):
            raise MemoryPatchError(ErrorCode.TARGET_DENIED)


def open_admitted_handle(
    handle: CoreDatabaseHandle,
    target: TargetIdentity,
    allowlist: TargetAllowlist,
    denylist: JuryDenylist,
):
    """No caller-supplied URI or post-admission target substitution."""
    if type(handle) is not CoreDatabaseHandle or type(target) is not TargetIdentity:
        raise MemoryPatchError(ErrorCode.TARGET_DENIED)
    allowlist.require_allowed(target)
    denylist.require_clear(target)
    opened = handle.open_connection(target, handle.role)
    connection = getattr(opened, "connection", None)
    try:
        if (
            type(opened) is not CoreOpenedConnection
            or opened.target_fingerprint != target.fingerprint
            or opened.verified_ca_fingerprint != target.certificate_fingerprint
            or opened.verify_full is not True
            or not connection.pgconn.ssl_in_use
            or connection.autocommit is not True
        ):
            raise MemoryPatchError(ErrorCode.TARGET_DENIED)
        peer = socket.socket(fileno=connection.pgconn.socket)
        try:
            address = peer.getpeername()
        finally:
            peer.detach()
        if address[:2] != (target.address, target.port):
            raise MemoryPatchError(ErrorCode.TARGET_DENIED)
        with connection.cursor() as cursor:
            cursor.execute("SELECT session_user, current_user, current_database()")
            if cursor.fetchone() != (handle.role, handle.role, target.database):
                raise MemoryPatchError(ErrorCode.TARGET_DENIED)
            cursor.execute(
                "SELECT rolsuper, rolcreaterole, rolcreatedb, rolbypassrls, "
                "pg_catalog.pg_has_role(session_user, 'admin', 'MEMBER') "
                "FROM pg_catalog.pg_roles WHERE rolname = session_user"
            )
            role = cursor.fetchone()
            if not role or role[0] or role[3] or role[4]:
                raise MemoryPatchError(ErrorCode.TARGET_DENIED)
            if handle.purpose is not DatabasePurpose.MIGRATOR and (role[1] or role[2]):
                raise MemoryPatchError(ErrorCode.TARGET_DENIED)
        return connection
    except BaseException:
        if connection is not None:
            connection.close()
        raise


_PURPOSES = {
    Capability.READ: frozenset({DatabasePurpose.APPLICATION, DatabasePurpose.AUDIT}),
    Capability.CANDIDATE: frozenset({DatabasePurpose.APPLICATION}),
    Capability.PROPOSE: frozenset({DatabasePurpose.APPLICATION}),
    Capability.VALIDATE: frozenset({DatabasePurpose.APPLICATION}),
    Capability.OWNER_APPROVAL: frozenset({DatabasePurpose.APPLICATION}),
    Capability.MANAGE: frozenset({DatabasePurpose.APPLICATION}),
    Capability.COMMIT: frozenset({DatabasePurpose.COMMIT}),
    Capability.ACTIVATE: frozenset({DatabasePurpose.COMMIT}),
    Capability.REVIEW: frozenset({DatabasePurpose.REVIEW}),
    Capability.EVIDENCE_CAPTURE: frozenset(
        {DatabasePurpose.INGESTION, DatabasePurpose.PUBLICATION}
    ),
}


@dataclass(slots=True, repr=False)
class ConnectionLease:
    connection: Any = field(repr=False)
    handle: CoreDatabaseHandle
    capability: Capability
    _pool: Any = field(repr=False)
    released: bool = False


class CorePurposePool:
    """A bounded local pool, inert until a current Core principal requests use."""

    def __init__(
        self,
        core: CoreAdmission,
        target: TargetIdentity,
        allowlist: TargetAllowlist,
        denylist: JuryDenylist,
        handles: tuple[tuple[Capability, CoreDatabaseHandle], ...],
        *,
        maximum_idle: int = 4,
    ):
        if type(handles) is not tuple or not 1 <= maximum_idle <= 8:
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        self._handles = dict(handles)
        if len(self._handles) != len(handles):
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        for capability, handle in handles:
            if (
                type(capability) is not Capability
                or type(handle) is not CoreDatabaseHandle
                or handle.purpose not in _PURPOSES.get(capability, frozenset())
                or handle.role == target.migrator_role
            ):
                raise MemoryPatchError(ErrorCode.ADMISSION_DENIED)
        self.core = core
        self.target = target
        self.allowlist = allowlist
        self.denylist = denylist
        self._maximum_idle = maximum_idle
        self._idle: list[tuple[CoreDatabaseHandle, Any]] = []
        self._leases: list[ConnectionLease] = []
        self._lock = threading.RLock()
        self._closed = False

    def acquire(self, context: TransactionContext) -> ConnectionLease:
        self.core.require(context.principal, context.purpose, scope=context.scope)
        self.allowlist.require_allowed(self.target)
        self.denylist.require_clear(self.target)
        with self._lock:
            if self._closed:
                raise MemoryPatchError(ErrorCode.MODULE_CLOSED)
            handle = self._handles.get(context.purpose)
            if handle is None:
                raise MemoryPatchError(ErrorCode.ADMISSION_DENIED)
            connection = None
            for index, (existing_handle, candidate) in enumerate(self._idle):
                if existing_handle is handle:
                    connection = candidate
                    self._idle.pop(index)
                    break
            if connection is None:
                connection = open_admitted_handle(
                    handle, self.target, self.allowlist, self.denylist
                )
            lease = ConnectionLease(connection, handle, context.purpose, self)
            self._leases.append(lease)
            return lease

    def release(self, lease: ConnectionLease, *, discard: bool = False):
        with self._lock:
            if lease._pool is not self or lease.released:
                raise MemoryPatchError(ErrorCode.TRANSACTION_FAILED)
            lease.released = True
            self._leases = [
                existing for existing in self._leases if existing is not lease
            ]
            connection = lease.connection
            try:
                connection.rollback()
                if not discard and not self._closed:
                    with connection.cursor() as cursor:
                        cursor.execute("RESET ROLE")
                        cursor.execute(
                            "SELECT aioa_memory_patch.clear_request_context()"
                        )
                        if cursor.fetchone() != (True,):
                            raise MemoryPatchError(ErrorCode.TRANSACTION_FAILED)
                        cursor.execute("RESET ALL")
                    if len(self._idle) < self._maximum_idle:
                        self._idle.append((lease.handle, connection))
                        return
            finally:
                if not any(candidate is connection for _, candidate in self._idle):
                    connection.close()

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            for _, connection in self._idle:
                connection.close()
            self._idle.clear()
            # An active transaction owns its lease until finally/rollback.
            # Closing the pool prevents any subsequent acquisition/reuse.
