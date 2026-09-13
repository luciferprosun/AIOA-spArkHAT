"""Native whole-transaction adapter; Core owns admission and retry policy."""

from __future__ import annotations

import hashlib
import secrets
import threading

from runtime.core_admission import CoreAdmission
from runtime.memory_patch.adapters.cockroach.pool import (
    CoreDatabaseHandle,
    CorePurposePool,
    DatabasePurpose,
    open_admitted_handle,
)
from runtime.memory_patch.adapters.cockroach.repositories import ScopedSQLRepository
from runtime.memory_patch.errors import ErrorCode, MemoryPatchError
from runtime.memory_patch.persistence.ports import TransactionContext


class CoreContextBroker:
    """A narrow Core capability projection into transaction-bound SQL tickets.

    The broker has no domain-table grant. Its credentials are an existing Core
    opaque handle, never environment data or a separate credential service.
    """

    def __init__(self, core: CoreAdmission, pool: CorePurposePool, handle):
        if (
            type(handle) is not CoreDatabaseHandle
            or handle.purpose is not DatabasePurpose.CONTEXT
            or handle.role == pool.target.migrator_role
            or core is not pool.core
        ):
            raise MemoryPatchError(ErrorCode.ADMISSION_DENIED)
        self._core, self._pool, self._handle = core, pool, handle

    def issue(self, context: TransactionContext, lease):
        self._core.require(context.principal, context.purpose, scope=context.scope)
        if lease._pool is not self._pool or lease.released:
            raise MemoryPatchError(ErrorCode.TRANSACTION_FAILED)
        # The application is still in autocommit mode. The broker commits the
        # ticket before BEGIN, so the application transaction can see the grant.
        with lease.connection.cursor() as cursor:
            cursor.execute("SELECT session_user, pg_catalog.pg_backend_pid()")
            database_user, backend_pid = cursor.fetchone()
        if database_user != lease.handle.role:
            raise MemoryPatchError(ErrorCode.TARGET_DENIED)
        ticket = secrets.token_urlsafe(32)
        ticket_hash = hashlib.sha256(ticket.encode()).hexdigest()
        connection = open_admitted_handle(
            self._handle,
            self._pool.target,
            self._pool.allowlist,
            self._pool.denylist,
        )
        try:
            principal = context.principal
            self._core.require(principal, context.purpose, scope=context.scope)
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT aioa_memory_patch.mint_context_ticket("
                    "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::STRING[],%s::STRING[],%s)",
                    (
                        ticket_hash,
                        database_user,
                        backend_pid,
                        *context.scope.binding(),
                        context.purpose.value,
                        principal.actor.value,
                        principal.actor_session_id,
                        sorted(principal.hat_ids),
                        sorted(principal.model_binding_ids),
                        principal.expires_at,
                    ),
                )
                if cursor.fetchone() != (True,):
                    raise MemoryPatchError(ErrorCode.ADMISSION_DENIED)
            return ticket
        finally:
            connection.close()


class CockroachTransaction:
    def __init__(self, factory, lease, context):
        self._factory, self._lease, self._context = factory, lease, context
        self._active = True
        self._committed = False
        self._closed = False
        self._repository = ScopedSQLRepository(
            lease.connection, context, self._check_active
        )

    def _check_active(self):
        if not self._active or self._closed or self._factory.closed:
            raise MemoryPatchError(ErrorCode.TRANSACTION_FAILED)
        self._factory.pool.core.require(
            self._context.principal, self._context.purpose, scope=self._context.scope
        )

    def get(self, kind, record_id):
        return self._repository.get(kind, record_id)

    def scan(self, kind, *, limit, states):
        return self._repository.scan(kind, limit=limit, states=states)

    def insert(self, record):
        self._repository.insert(record)

    def replace(self, record, *, expected_revision):
        self._repository.replace(record, expected_revision=expected_revision)

    def commit(self):
        self._check_active()
        # Structured driver failures propagate to the existing C4 runner:
        # 40001 retries all computation; unknown acknowledgement reconciles.
        self._lease.connection.commit()
        self._committed = True
        self._active = False

    def rollback(self):
        if self._closed:
            return
        self._active = False
        self._lease.connection.rollback()

    def close(self):
        if self._closed:
            return
        self._closed = True
        self._active = False
        self._factory.pool.release(
            self._lease, discard=not self._committed or self._factory.closed
        )


class CockroachTransactionFactory:
    def __init__(self, pool: CorePurposePool, broker: CoreContextBroker):
        if broker._pool is not pool:
            raise MemoryPatchError(ErrorCode.ADMISSION_DENIED)
        self.pool, self.broker = pool, broker
        self.closed = False
        self._lock = threading.RLock()

    def begin(self, context: TransactionContext, *, attempt: int):
        if type(attempt) is not int or not 1 <= attempt <= 10:
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        with self._lock:
            if self.closed:
                raise MemoryPatchError(ErrorCode.MODULE_CLOSED)
            self.pool.core.require(
                context.principal, context.purpose, scope=context.scope
            )
            lease = self.pool.acquire(context)
            try:
                ticket = self.broker.issue(context, lease)
                with lease.connection.cursor() as cursor:
                    cursor.execute("BEGIN ISOLATION LEVEL SERIALIZABLE")
                    cursor.execute(
                        "SELECT aioa_memory_patch.set_request_context(%s)", (ticket,)
                    )
                    if cursor.fetchone() != (True,):
                        raise MemoryPatchError(ErrorCode.ADMISSION_DENIED)
                    cursor.execute("SHOW TRANSACTION ISOLATION LEVEL")
                    if cursor.fetchone()[0].lower() != "serializable":
                        raise MemoryPatchError(ErrorCode.TRANSACTION_FAILED)
                return CockroachTransaction(self, lease, context)
            except BaseException:
                self.pool.release(lease, discard=True)
                raise

    def close(self):
        with self._lock:
            if self.closed:
                return
            self.closed = True
            self.pool.close()
