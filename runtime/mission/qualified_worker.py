"""Host-created, bounded WorkerPort for one Nebius advice request.

Preparing a mailbox and operation does no I/O to the provider. Only a fresh
paid Core START and matching one-use transport permit release one request.
Transport uncertainty leaves the original paid reservation held for independent
reconciliation. A candidate is inert and belongs to the existing validator.
"""

import hashlib
import json
import re
import threading
import time
from contextlib import nullcontext
from dataclasses import dataclass, field
from pathlib import Path

from runtime.core_admission import Capability
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.memory_patch.persistence.ports import RecordKind, StoredRecord
from runtime.mission.warrant import require as core_require
from runtime.mission.intent import CoreIntentJournal
from runtime.mission.worker import (
    Task,
    WorkerFailure,
    WorkerResult,
    WorkerMailbox,
    WorkerOutcomeUnknown,
    require,
)
from runtime.providers.exact import (
    CancellationToken,
    ExactRequest,
    exact_request_body,
    generate_http_exact,
)
from runtime.providers.live_gate import LiveCallGate, require_transport_authorization
from runtime.providers.messages import ChatMessage

MODEL = "nvidia/Nemotron-3_5-Lightning"
BASE_URL = "https://api.tokenfactory.nebius.com/v1"
OP_CLASS = "MODEL_WORKER_ADVICE_V1"
# USD per million tokens: input 0.06, output (including reasoning) 0.24.
# These are maximum accepted rates. The host must recheck its billing terms.
MAX_COST_NANO = 2048 * 60 + 256 * 240
_HEX = re.compile(r"[a-f0-9]{64}\Z")


@dataclass(frozen=True, slots=True)
class _Connection:
    base_url: str
    api_key: str = field(repr=False)
    provider: str = "nebius"
    model: str = MODEL


def worker_lease_digest(principal, epoch):
    return canonical_sha256(
        {
            "scope": canonical_sha256(principal.scope),
            "epoch": epoch,
            "assignment_revision": principal.assignment_revision,
            "session_id": principal.actor_session_id,
        }
    )


def verify_worker_operation(operation, warrant, reservation, principal):
    """Check cost and scope again inside the existing durable START transaction."""
    p = operation["payload"]
    required = {
        "schema",
        "session_id",
        "epoch",
        "task_id",
        "task_digest",
        "worker_session_id",
        "workspace_id",
        "repository_id",
        "source_sha",
        "capsule_digest",
        "lease_digest",
        "permit_digest",
        "adapter_digest",
        "wire_sha256",
        "endpoint",
        "scope",
        "price_checked_at",
        "provider",
        "model",
        "max_cost_nano",
        "deadline_at",
    }
    core_require(
        type(p) is dict
        and set(p) == required
        and p["schema"] == "aioa.worker-model-call.v1"
        and operation["operation_class"] == OP_CLASS
        and p["task_id"] == warrant.task_id
        and p["epoch"] == warrant.lease_epoch
        and p["session_id"] == principal.actor_session_id
        and p["scope"] in ("TEST", "LIVE")
        and p["provider"] == reservation.provider_id == "nebius"
        and p["model"] == reservation.model_id == MODEL
        and all(
            type(p[k]) is str and _HEX.fullmatch(p[k])
            for k in (
                "task_digest",
                "capsule_digest",
                "lease_digest",
                "permit_digest",
                "adapter_digest",
                "wire_sha256",
            )
        )
        and p["lease_digest"] == worker_lease_digest(principal, warrant.lease_epoch)
        and p["source_sha"]
        and re.fullmatch(r"[0-9a-f]{40}", p["source_sha"])
        and (
            p["endpoint"] == BASE_URL + "/chat/completions"
            if p["scope"] == "LIVE"
            else bool(
                re.fullmatch(
                    r"http://127[.]0[.]0[.]1:[0-9]{1,5}/v1/chat/completions",
                    p["endpoint"],
                )
            )
        )
        and type(p["deadline_at"]) is int
        and type(p["price_checked_at"]) is int
        and operation["target_fingerprint"] == "sha256:" + canonical_sha256(p)
        and p["max_cost_nano"] == reservation.money_nano == MAX_COST_NANO
        and warrant.authority_scope.monetary_ceiling.currency == "USD"
        and MAX_COST_NANO
        <= warrant.authority_scope.monetary_ceiling.amount * 10**9
        <= 10_000_000,
        "WORKER_START_BINDING",
    )


class QualifiedModelWorker:
    def __init__(
        self,
        task,
        *,
        gate,
        capsule_digest,
        lease_digest,
        price_checked_at,
        connection,
        scope,
    ):
        require(
            type(task) is Task
            and task.max_output_tokens <= 256
            and type(gate) is LiveCallGate
            and gate.permit is not None
            and gate.permit.max_live_calls == 1
            and gate.permit.transport_scope == scope,
            "WORKER_PERMIT_BINDING",
        )
        require(
            all(
                type(d) is str and _HEX.fullmatch(d)
                for d in (capsule_digest, lease_digest)
            )
            and type(price_checked_at) is int
            and type(connection) is _Connection
            and type(connection.api_key) is str
            and 1 <= len(connection.api_key) <= 2048
            and all(32 < ord(char) < 127 for char in connection.api_key)
            and (
                (
                    scope == "LIVE"
                    and connection.base_url == BASE_URL
                    and connection.api_key
                )
                or (
                    scope == "TEST"
                    and re.fullmatch(
                        r"http://127[.]0[.]0[.]1:[0-9]{1,5}/v1", connection.base_url
                    )
                    and connection.api_key == "fixture"
                )
            ),
            "WORKER_HOST_BINDING",
        )
        self.mailbox = WorkerMailbox(task, worker_id="nebius-worker")
        self.connection, self.scope, self.gate = connection, scope, gate
        self.pins = {
            "capsule_digest": capsule_digest,
            "lease_digest": lease_digest,
            "price_checked_at": price_checked_at,
        }
        s = self.mailbox.session
        envelope = {
            "schema": "aioa.worker-candidate.v1",
            "task_id": s.task_id,
            "run_id": s.run_id,
            "session_id": s.session_id,
            "task_digest": s.task_digest,
            "files": [{"path": "...", "text": "..."}],
        }
        self.request = ExactRequest(
            "nebius",
            MODEL,
            (
                ChatMessage(
                    "system",
                    "Return only a JSON candidate with these exact bindings and proposed files: "
                    + json.dumps(envelope, separators=(",", ":")),
                ),
                ChatMessage("user", task.instruction),
            ),
            task.max_output_tokens,
            max_input_tokens=2048,
            max_response_bytes=16384,
            timeout_seconds=20,
            transport_scope=scope,
            bound_reasoning_tokens=True,
        )
        self.request.validate()
        self._bound = None
        self._started = self._released = self._sending = self._closed = False
        self._live_host = self._signature = None
        self._lock = threading.Lock()
        self._token = CancellationToken()
        self.provider_receipt = None
        self._receipt_failure = None
        self._finished = False

    @classmethod
    def live(cls, task, *, api_key, **pins):
        return cls(
            task, connection=_Connection(BASE_URL, api_key), scope="LIVE", **pins
        )

    @classmethod
    def loopback(cls, task, *, port, **pins):
        require(type(port) is int and 0 < port <= 65535, "WORKER_LOOPBACK_PORT")
        return cls(
            task,
            connection=_Connection(f"http://127.0.0.1:{port}/v1", "fixture"),
            scope="TEST",
            **pins,
        )

    def operation(self, principal, epoch):
        task = self.mailbox.task
        payload = {
            **self.pins,
            "schema": "aioa.worker-model-call.v1",
            "session_id": principal.actor_session_id,
            "epoch": epoch,
            "task_id": task.task_id,
            "task_digest": task.digest,
            "worker_session_id": self.mailbox.session.session_id,
            "workspace_id": task.workspace_id,
            "repository_id": task.repository_id,
            "source_sha": task.source_base_sha,
            "permit_digest": self.gate.permit.permit_digest,
            "adapter_digest": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "wire_sha256": hashlib.sha256(exact_request_body(self.request)).hexdigest(),
            "endpoint": self.connection.base_url + "/chat/completions",
            "scope": self.scope,
            "provider": "nebius",
            "model": MODEL,
            "max_cost_nano": MAX_COST_NANO,
            "deadline_at": task.deadline_at,
        }
        return {
            "operation_class": OP_CLASS,
            "target_fingerprint": "sha256:" + canonical_sha256(payload),
            "expected_target_revision": self.gate.permit.git_sha,
            "payload": payload,
        }

    def approval_proof(self, principal, warrant, reservation):
        """Canonical unsigned payload for the qualified operator's Core signer."""
        return {
            "schema": "aioa.worker-owner-release.v1",
            "warrant_digest": warrant.digest(),
            "operation": self.operation(principal, warrant.lease_epoch),
            "reservation_digest": canonical_sha256(reservation),
        }

    def _qualified_host(self, journal, principal, warrant, reservation):
        from runtime.meta_hackathon.runtime_adapter import NativeMobileComposition
        from runtime.mobile_gateway.wire import verify

        host = self._live_host
        require(
            type(host) is NativeMobileComposition
            and host.foundation is not None
            and journal is host.intent_journal is host.foundation.intent_journal
            and journal.ledger is host.ledger
            and journal.governor is host.foundation.governor
            and host.core is journal.ledger.core
            and host.missions.runner is journal.ledger.runner
            and host.missions.scope == journal.ledger.scope
            and host.foundation.spec.to_dict()["profile"] == "OWNED_WORKER_MODEL_B_V1",
            "QUALIFIED_WORKER_HOST_REQUIRED",
        )
        host.foundation.require_bindings()
        host.missions._native_execution_gate()
        host._require_qualified_operator()
        require(
            host.source == (self.gate.permit.git_sha, self.pins["capsule_digest"])
            and host.operator_principal().actor_session_id
            == principal.actor_session_id,
            "WORKER_SOURCE_OR_SESSION_CHANGED",
        )
        verify(
            host.identity.spki,
            self._signature,
            self.approval_proof(principal, warrant, reservation),
        )

    def bind(
        self,
        journal,
        principal,
        warrant,
        reservation,
        *,
        native_host=None,
        approval_signature=None,
    ):
        require(type(journal) is CoreIntentJournal, "WORKER_CORE_REQUIRED")
        with self._lock:
            require(self._bound is None and not self._started, "WORKER_ALREADY_BOUND")
            if self.scope == "LIVE":
                self._live_host, self._signature = native_host, approval_signature
                self._qualified_host(journal, principal, warrant, reservation)
            self._bound = (journal, principal, warrant, reservation)

    def _check_time(self):
        now = time.time()
        require(
            0 < self.mailbox.task.deadline_at - now <= 60
            and 0 <= now - self.pins["price_checked_at"] <= 86400,
            "WORKER_WINDOW",
        )

    def start(self, task):
        with self._lock:
            require(
                not self._started
                and not self._closed
                and self._bound is not None
                and type(task) is Task
                and task == self.mailbox.task,
                "WORKER_START_DENIED",
            )
            self._started = True
        self._check_time()
        self.gate.require("nebius", MODEL, self.scope)
        journal, principal, warrant, reservation = self._bound
        if self.scope == "LIVE":
            self._qualified_host(journal, principal, warrant, reservation)
        released = journal.start_paid_worker(
            principal,
            warrant,
            self.operation(principal, warrant.lease_epoch),
            reservation,
        )
        if released["worker_step_now"] is not True:
            raise WorkerOutcomeUnknown()
        with self._lock:
            if self._closed:
                raise WorkerOutcomeUnknown()
            self._released = True
        return self.mailbox.session

    def _release(self, body):
        self._check_time()
        journal, principal, warrant, reservation = self._bound
        if self.scope == "LIVE":
            self._qualified_host(journal, principal, warrant, reservation)

        operation = self.operation(principal, warrant.lease_epoch)
        release = {
            "proof": self.approval_proof(principal, warrant, reservation),
            "signature": self._signature,
        }

        def check(tx):
            _, intent = journal._load(tx, warrant)
            journal.ledger.require_active_in_transaction(tx, warrant, consumed=True)
            state = journal.governor._load(tx)
            journal.governor._epoch(state, warrant.lease_epoch)
            require(
                not state["kill"]
                and intent is not None
                and intent["resolution"] is None
                and intent["reservation"] == canonical_sha256(reservation)
                and intent["operation"] == operation
                and intent["operation"]["payload"]["wire_sha256"]
                == hashlib.sha256(body).hexdigest(),
                "WORKER_RELEASE_DENIED",
            )
            if self.scope == "LIVE":
                tx.insert(
                    StoredRecord(
                        RecordKind.RECEIPT,
                        "worker-release-" + canonical_sha256(warrant.digest()),
                        journal.ledger.scope,
                        1,
                        release,
                    )
                )

        journal._run(principal, Capability.COMMIT, check)
        params = dict(
            transport=self.connection,
            payload=body,
            timeout=self.request.timeout_seconds,
            max_bytes=self.request.max_response_bytes,
        )
        auth = self.gate.authorize("nebius", MODEL, self.scope, **params)
        require_transport_authorization(
            auth, self.scope, provider_id="nebius", model_id=MODEL, **params
        )

    def poll(self, session):
        self.mailbox._check(session)
        with self._lock:
            require(self._released, "WORKER_NOT_RELEASED")
            send = not self._sending and not self._closed
            self._sending = True
        if send:
            try:
                self._check_time()
                deadline = (
                    time.monotonic() + self.mailbox.task.deadline_at - time.time()
                )
                guard = (
                    self._live_host.missions._native_synchronous(
                        session.session_id, "WORKER_MODEL_CALL"
                    )
                    if self.scope == "LIVE"
                    else nullcontext(None)
                )
                with guard as handle:
                    with self._lock:
                        require(not self._closed, "WORKER_CLOSED")
                        if self.scope == "LIVE":
                            require(handle is not None, "NATIVE_WORKER_HANDLE_REQUIRED")
                            self._token = handle.cancel
                    result = generate_http_exact(
                        self.connection,
                        self.request,
                        self._token,
                        deadline,
                        fixture=self.scope == "TEST",
                        before_send=self._release,
                    )
                    with self._lock:
                        require(
                            not self._closed and not self._token.cancelled,
                            "WORKER_CLOSED",
                        )
                        self._accept_result(session, result)
            except Exception:
                with self._lock:
                    self._receipt_failure = WorkerFailure(
                        session.session_id,
                        session.task_id,
                        session.run_id,
                        "OUTCOME_UNKNOWN",
                    )
                    self.mailbox.fail(session, "OUTCOME_UNKNOWN")
            finally:
                with self._lock:
                    self._finished = True
        with self._lock:
            if self._sending and not self._finished and not self._closed:
                return ()
            events = self.mailbox.drain(session)
            if self._receipt_failure:
                return tuple(
                    event
                    for event in events
                    if event.kind not in ("CANDIDATE", "COMPLETED")
                )
            return events

    def _accept_result(self, session, result):
        usage = result.usage
        require(
            result.request_id
            and usage
            and set(usage) == {"prompt_tokens", "completion_tokens", "total_tokens"}
            and usage["prompt_tokens"] > 0
            and usage["completion_tokens"] > 0
            and usage["total_tokens"]
            == usage["prompt_tokens"] + usage["completion_tokens"],
            "WORKER_USAGE_UNVERIFIED",
        )
        self.mailbox.complete_json(
            session,
            result.content.encode("utf-8"),
            completion_tokens=usage["completion_tokens"],
        )
        candidate = self.mailbox.result(session)
        receipt = {
            "schema": "aioa.qualified-worker-observation.v1",
            "authority": "NONE",
            "scope": self.scope,
            "task_digest": session.task_digest,
            "worker_session_id": session.session_id,
            "model": result.reported_model,
            "request_id_sha256": hashlib.sha256(result.request_id.encode()).hexdigest(),
            "usage": usage,
            "candidate_digest": candidate.candidate.digest
            if type(candidate) is WorkerResult
            else None,
            "mailbox_status": candidate.status,
            "permit_digest": self.gate.permit.permit_digest,
        }
        journal, principal, warrant, reservation = self._bound
        receipt.update(
            warrant_digest=warrant.digest(),
            operation_hash=warrant.operation_hash,
            reservation_digest=canonical_sha256(reservation),
        )
        packet = {
            "receipt": receipt,
            "signature": self._live_host.identity.sign(receipt)
            if self.scope == "LIVE"
            else None,
        }
        row = StoredRecord(
            RecordKind.RECEIPT,
            "worker-" + canonical_sha256(receipt["warrant_digest"]),
            journal.ledger.scope,
            1,
            packet,
        )
        journal._run(principal, Capability.COMMIT, lambda tx: tx.insert(row))
        self.provider_receipt = packet

    def result(self, session):
        with self._lock:
            self.mailbox._check(session)
            if self._sending and not self._finished and not self._closed:
                return None
            return self._receipt_failure or self.mailbox.result(session)

    def cancel(self, session):
        self.mailbox._check(session)
        self.close()

    interrupt = cancel

    def close(self):
        with self._lock:
            self._closed = True
            started = self._started
            if started and not self._finished:
                s = self.mailbox.session
                self._receipt_failure = WorkerFailure(
                    s.session_id, s.task_id, s.run_id, "OUTCOME_UNKNOWN"
                )
        self._token.cancel()
        self.mailbox.fail(
            self.mailbox.session, "OUTCOME_UNKNOWN" if started else "CLOSED"
        )
