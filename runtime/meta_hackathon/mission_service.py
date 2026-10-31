"""One bounded mission facade over existing Core records and P01 READ.

Model output is advisory. No credential loading, owner admission, standalone
database, browser process or paid transport is constructed here.
"""
from dataclasses import dataclass, replace
from datetime import timedelta, timezone
from decimal import Decimal
from enum import Enum
import hashlib
import json
import threading
import uuid

from lab.archaioa.authority import AuthorityScope, Money, RiskLevel
from lab.archaioa.decision_root import DecisionDependencyRoot
from lab.archaioa.evidence import EvidenceRef
from lab.archaioa.warrant import EffectWarrant, RevisionPolicy
from runtime.browser_agent.chrome_read_adapter import OfflineFixtureRead
from runtime.browser_agent.offline_adapter import FIXTURE_ORIGIN, FIXTURE_TEXT, FIXTURE_URL
from runtime.core_admission import Capability
from runtime.memory_patch.contracts.serialization import canonical_json_bytes, canonical_sha256
from runtime.memory_patch.persistence.ports import RecordKind, StoredRecord, TransactionContext
from runtime.mission.warrant import CoreWarrantLedger, approval_digest
from runtime.providers.exact import CancellationToken
from runtime.providers.meta_model_api import MetaPlanRequest, MODEL, PROVIDER, MetaAPIError
from runtime.providers.tool_calling import ToolCall
from .contracts import BrowserTaskV1
from .mission_read_offline import read_operation, run_read_once
from .offline_receipts import BudgetReservation, MOCK_RESPONSE_SCHEMA, OfflineReceiptLedger
from .provider_offline import build_offline_envelope

KIND = 'aioa.meta.mission.v1'
ACTIVE = frozenset({'PREVIEWED', 'RUNNING'})


class MissionState(str, Enum):
    PREVIEWED = 'PREVIEWED'
    RUNNING = 'RUNNING'
    OFFLINE_FIXTURE = 'OFFLINE_FIXTURE'
    LIVE_PENDING_AUTHORIZATION = 'LIVE_PENDING_AUTHORIZATION'
    LIVE_VERIFIED = 'LIVE_VERIFIED'
    UNKNOWN = 'UNKNOWN'
    DENIED = 'DENIED'
    STOPPED = 'STOPPED'


TRANSITIONS = {'PREVIEWED': {'RUNNING', 'UNKNOWN', 'DENIED', 'STOPPED'},
               'RUNNING': {'OFFLINE_FIXTURE', 'UNKNOWN', 'STOPPED'},
               'LIVE_PENDING_AUTHORIZATION': {'STOPPED'}}


class MissionError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def require(value, code='META_MISSION_DENIED'):
    if not value: raise MissionError(code)


def plain(value): return json.loads(canonical_json_bytes(value))
def utc(value): return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


@dataclass(frozen=True)
class MissionRequest:
    instruction: str
    mode: str
    target_url: str

    @classmethod
    def parse(cls, value):
        require(type(value) is dict and set(value) == {'instruction', 'mode', 'target_url'})
        require(type(value['instruction']) is str and 1 <= len(value['instruction'].encode()) <= 2000)
        require(value['mode'] in ('OFFLINE_FIXTURE', 'LIVE') and value['target_url'] == FIXTURE_URL)
        return cls(**value)


def make_mock_receipt(task, correlation_id, now):
    """Existing receipt ledger with 0 USD; never a substitute for a LIVE result."""
    envelope = build_offline_envelope(task, 'Bounded offline task', budget_usd_limit=0.0)
    reservation = BudgetReservation(task.digest, task.owner_scope_digest, task.source_sha, MODEL,
        correlation_id, canonical_sha256(correlation_id), utc(now), utc(now+timedelta(minutes=2)), 512, '0.00')
    raw = {'schema': MOCK_RESPONSE_SCHEMA, 'model': MODEL, 'task_digest': task.digest,
        'owner_scope_digest': task.owner_scope_digest, 'source_sha': task.source_sha,
        'attempt_id': correlation_id, 'nonce_sha256': reservation.nonce_sha256,
        'completion_tokens': 0, 'status': 'MOCK_DONE'}
    return OfflineReceiptLedger(max_total_usd='0.00').record_once(reservation, envelope,
        mock_response_json=json.dumps(raw), mock_cost_usd='0.00', now_utc=utc(now))


class MissionService:
    def __init__(self, ledger, manager, browser, source_probe):
        require(type(ledger) is CoreWarrantLedger)
        self.ledger, self.core, self.runner, self.scope = ledger, ledger.core, ledger.runner, ledger.scope
        self.manager, self.browser, self.source_probe = manager, browser, source_probe
        self._lock = threading.RLock()
        self._workers, self._cancels = {}, {}
        self._closed = False
        # Pending work is never resumed on restart; old ACKs cannot grant dispatch.
        for row in self._rows():
            if row.payload['state'] in ACTIVE:
                self._change(row.record_id, ACTIVE, 'UNKNOWN', {'error': 'RESTART_READBACK_REQUIRED'})

    def _run(self, purpose, callback):
        principal = self.core.local_operator(purpose)
        return self.runner.run(TransactionContext(principal, purpose), callback)

    def _rows(self):
        def read(tx):
            # The existing port applies state filtering before LIMIT. Warrant
            # rows must not crowd missions out of active/restart checks.
            rows = tx.scan(RecordKind.OPERATION, limit=1024, states=tuple(state.value for state in MissionState))
            require(len(rows) < 1024, 'META_MISSION_HISTORY_LIMIT')
            return tuple(row for row in rows if row.payload.get('schema') == KIND)
        return self._run(Capability.READ, read)

    def _get(self, identity):
        require(type(identity) is str and identity.startswith('meta-') and len(identity) <= 80)
        row = self._run(Capability.READ, lambda tx: tx.get(RecordKind.OPERATION, identity))
        require(row is not None and row.payload.get('schema') == KIND, 'META_MISSION_NOT_FOUND')
        return row

    def _change(self, identity, allowed, state, updates=None):
        def change(tx):
            row = tx.get(RecordKind.OPERATION, identity)
            require(row is not None and row.payload.get('schema') == KIND, 'META_MISSION_NOT_FOUND')
            data = plain(row.payload)
            if data['state'] not in allowed: return data
            require(state in TRANSITIONS.get(data['state'], ()), 'META_STATE_TRANSITION_DENIED')
            MissionState(state)
            data.update(updates or {}, state=state)
            tx.replace(StoredRecord(RecordKind.OPERATION, identity, self.scope, row.revision+1, data),
                       expected_revision=row.revision)
            return data
        return self._run(Capability.COMMIT, change)

    def preview(self, payload, principal):
        self.core.require(principal, Capability.READ, scope=self.scope)
        request = MissionRequest.parse(payload)
        with self._lock:
            require(not self._closed, 'META_SERVICE_CLOSED')
            require(not any(row.payload['state'] in ACTIVE for row in self._rows()), 'META_MISSION_ACTIVE')
            now = self.ledger.clock(); sha, capsule = self.source_probe()
            identity, correlation = 'meta-'+uuid.uuid4().hex, 'meta-corr-'+uuid.uuid4().hex
            task = BrowserTaskV1(task_id=identity, owner_scope_digest=canonical_sha256(self.scope),
                source_sha=sha, allowed_origins=(FIXTURE_ORIGIN,), target_url=FIXTURE_URL,
                deadline_utc=utc(now+timedelta(minutes=2)), operation='navigate_read',
                max_pages=1, timeout_ms=8000, max_chars=1600)
            record = {'schema': KIND, 'task_id': identity, 'task_digest': task.digest,
                'owner_scope_digest': task.owner_scope_digest, 'source_sha': sha,
                'capsule_digest': capsule, 'provider_id': PROVIDER, 'model_id': MODEL,
                'deadline': task.deadline_utc, 'budget_usd': '0', 'allowed_origins': list(task.allowed_origins),
                'correlation_id': correlation, 'stopped': False, 'mode': request.mode,
                'state': 'LIVE_PENDING_AUTHORIZATION' if request.mode == 'LIVE' else 'PREVIEWED',
                'created_at': utc(now), 'created_order': int(now.timestamp()*1000000),
                'verified': False, 'live_verified': False, 'dispatch_allowed': False,
                'task': task.to_dict(), 'instruction_sha256': hashlib.sha256(request.instruction.encode()).hexdigest(),
                'result': None, 'browser_receipt': None, 'provider_receipt': None, 'error': None}
            if request.mode == 'OFFLINE_FIXTURE':
                proposal = self.manager.generate_meta_plan(MetaPlanRequest(task, request.instruction, correlation,
                                                                          capsule_digest=capsule),
                                                           CancellationToken())
                record['proposal'] = proposal.call.to_wire()
                record['provider_receipt'] = proposal.receipt()
            else:
                record['proposal'] = None
                record['error'] = 'META_API_LIVE_BLOCKED_OWNER_GO'
            record['preview_digest'] = canonical_sha256(record)
            self._run(Capability.COMMIT, lambda tx: tx.insert(StoredRecord(RecordKind.OPERATION,
                                identity, self.scope, 1, record)))
            return plain(record)

    def _warrant(self, record, operation, now):
        expires = min(now+timedelta(seconds=60), __import__('datetime').datetime.fromisoformat(record['deadline'].replace('Z', '+00:00')))
        scope = AuthorityScope(operation_classes=(operation['operation_class'],),
            target_scope=operation['target_fingerprint'], risk_ceiling=RiskLevel.LOW,
            monetary_ceiling=Money(Decimal(0), 'USD'), not_before=now, expires_at=expires,
            owner_scope=record['owner_scope_digest'], task_scope=record['task_id'])
        warrant = EffectWarrant(warrant_id='warrant-'+record['task_id'], task_id=record['task_id'],
            owner_scope=record['owner_scope_digest'], operation_class=operation['operation_class'],
            operation_hash='sha256:'+canonical_sha256(operation), target_fingerprint=operation['target_fingerprint'],
            expected_target_revision=record['source_sha'], revision_policy=RevisionPolicy.REQUIRE,
            decision_dependency_root=DecisionDependencyRoot((
                EvidenceRef('meta-task', 'task', 'sha256:'+record['task_digest'], 'v1'),
                EvidenceRef('meta-source', 'context', 'sha256:'+record['capsule_digest'], 'v1'),)),
            lease_epoch=0, authority_scope=scope, approval_digest='sha256:'+'0'*64,
            money_reservation_id='NONE', risk_reservation_id='NONE', nonce=record['correlation_id'],
            issued_at=now, expires_at=expires)
        return replace(warrant, approval_digest=approval_digest(warrant))

    def run(self, identity, preview_digest, owner_principal):
        self.core.require(owner_principal, Capability.OWNER_APPROVAL, scope=self.scope)
        with self._lock:
            record = plain(self._get(identity).payload)
            require(record['state'] != 'LIVE_PENDING_AUTHORIZATION', 'META_API_LIVE_BLOCKED_OWNER_GO')
            require(record['state'] == 'PREVIEWED' and record['preview_digest'] == preview_digest,
                    'META_MISSION_NOT_PREVIEWED')
            if self.source_probe() != (record['source_sha'], record['capsule_digest']):
                self._change(identity, {'PREVIEWED'}, 'DENIED', {'error': 'META_SOURCE_DRIFT'})
                raise MissionError('META_SOURCE_DRIFT')
            now = self.ledger.clock(); task = BrowserTaskV1.parse(record['task']); raw = record['proposal']
            call = ToolCall(raw['id'], raw['function']['name'], raw['function']['arguments'])
            operation = read_operation(task, call, expected_content_sha256=hashlib.sha256(FIXTURE_TEXT.encode()).hexdigest(), initial_utc=now)
            warrant = self._warrant(record, operation, now)
            try:
                self.ledger.approve(owner_principal, warrant)
                self._change(identity, {'PREVIEWED'}, 'RUNNING', {'warrant_digest': warrant.digest()})
            except Exception:
                self._change(identity, {'PREVIEWED', 'RUNNING'}, 'UNKNOWN', {'error': 'META_APPROVAL_ACK_UNKNOWN'})
                raise MissionError('META_APPROVAL_ACK_UNKNOWN') from None
            cancel = CancellationToken(); self._cancels[identity] = cancel
            thread = threading.Thread(target=self._execute, args=(record, task, call, warrant, cancel, now), daemon=True)
            self._workers[identity] = thread; thread.start()
            return self.evidence(identity, self.core.local_operator(Capability.READ))

    def _execute(self, record, task, call, warrant, cancel, initial):
        identity = record['task_id']
        try:
            reader = OfflineFixtureRead(self.browser, cancel, self.ledger.clock,
                lambda: self.source_probe() == (record['source_sha'], record['capsule_digest']))
            receipt = make_mock_receipt(task, record['correlation_id'], self.ledger.clock())
            result = run_read_once(ledger=self.ledger,
                read_principal=self.core.local_operator(Capability.READ),
                commit_principal=self.core.local_operator(Capability.COMMIT), task=task, call=call, warrant=warrant,
                current_source_sha=self.source_probe()[0], expected_content_sha256=hashlib.sha256(FIXTURE_TEXT.encode()).hexdigest(),
                initial_utc=initial, provider_receipt=receipt, cancel=cancel, fixture_reader=reader)
            state = 'STOPPED' if cancel.cancelled else ('OFFLINE_FIXTURE' if result['status'] == 'OFFLINE_LINKED_UNVERIFIED' else 'UNKNOWN')
            if reader.last_receipt is not None:
                reader.last_receipt.update(correlation_id=record['correlation_id'], provider_id=PROVIDER,
                    model_id=MODEL, deadline=record['deadline'], budget_usd='0',
                    allowed_origins=record['allowed_origins'], capsule_digest=record['capsule_digest'],
                    stopped=cancel.cancelled)
            self._change(identity, {'RUNNING'}, state, {'result': result, 'browser_receipt': reader.last_receipt,
                                                       'stopped': cancel.cancelled})
        except Exception:
            self._change(identity, {'RUNNING'}, 'STOPPED' if cancel.cancelled else 'UNKNOWN',
                         {'error': 'META_READBACK_UNKNOWN', 'stopped': cancel.cancelled})

    def evidence(self, identity, principal):
        self.core.require(principal, Capability.READ, scope=self.scope)
        return plain(self._get(identity).payload)

    def stop(self, identity, principal):
        self.core.require(principal, Capability.READ, scope=self.scope)
        with self._lock:
            cancel = self._cancels.get(identity)
            if cancel is not None: cancel.cancel()
            self._get(identity)
            self._change(identity, ACTIVE | {'LIVE_PENDING_AUTHORIZATION'}, 'STOPPED', {'stopped': True})
            return self.evidence(identity, principal)

    def status(self, principal):
        self.core.require(principal, Capability.READ, scope=self.scope)
        rows = sorted(self._rows(), key=lambda row: row.payload.get('created_order', 0))
        return {'schema': 'aioa.meta.mission-status.v1', 'mode': 'OFFLINE_FIXTURE',
            'provider': self.manager._meta_provider.diagnostics(),
            'chrome_live': 'BLOCKED_CONTAINMENT_AND_OWNER_GO', 'active_task_id': next((r.record_id for r in rows if r.payload['state'] in ACTIVE), None),
            'missions': [{'task_id': r.record_id, 'state': r.payload['state'],
                          'created_at': r.payload.get('created_at')} for r in rows],
            'live_verified': False, 'budget_usd': '0'}

    def close(self):
        self._closed = True
        for cancel in tuple(self._cancels.values()): cancel.cancel()
        for thread in tuple(self._workers.values()): thread.join(timeout=2)
