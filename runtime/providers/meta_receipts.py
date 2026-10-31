"""Redacted call observations in the existing scoped Core records.

These records cannot approve, reserve, settle or retry an operation. Authority
continues to live in CoreWarrantLedger/CoreDualGovernor. No new store is opened.
"""
import json

from runtime.core_admission import Capability
from runtime.memory_patch.contracts.serialization import canonical_json_bytes, canonical_sha256
from runtime.memory_patch.persistence.ports import RecordKind, StoredRecord
from runtime.mission.warrant import CoreWarrantLedger

KIND = 'aioa.meta.api-attempt.v1'
STATES = ('ADMITTED', 'IN_FLIGHT', 'COMPLETED', 'FAILED', 'UNKNOWN', 'STOPPED')
FILTER = tuple(KIND+':'+s for s in STATES)


def plain(value):
    return json.loads(canonical_json_bytes(value))


def require(ok):
    if not ok: raise ValueError('META_RECEIPT_INTEGRITY')


def _rows(tx):
    rows = tx.scan(RecordKind.OPERATION, limit=1024, states=FILTER)
    require(len(rows) < 1024)
    return tuple(r for r in rows if r.payload.get('schema') == KIND)


class MetaCallRecords:
    """CAS observation writes; receives already-admitted native composition."""
    def __init__(self, binding):
        self.binding = binding
        self.ledger = binding.ledger

    def admit(self, request):
        identity = 'meta-api-attempt-'+request.digest
        data = {'schema': KIND, 'state': KIND+':ADMITTED', 'attempt_id': identity,
            'attempt': 1, 'request_digest': request.digest, 'binding': request.public_binding(),
            'policy_epoch': self.binding.warrant.lease_epoch,
            'warrant_digest': self.binding.warrant.digest(),
            'nonce_digest': canonical_sha256(self.binding.warrant.nonce),
            'approval_record_id': self.ledger._key(self.binding.warrant),
            'operation_digest': self.binding.reservation.request_digest,
            'reservation_id': self.binding.reservation.request_id,
            'input_bound': len(canonical_json_bytes(request.payload()))+512,
            'output_bound': request.max_output_tokens,
            'cost_estimate': str(request.estimate()), 'settled_cost': None,
            'http_status': None, 'error_code': None,
            'created_at': self.ledger.clock().isoformat()}
        def write(tx):
            # Existing immutable identity and CAS provide the durable retry barrier.
            require(tx.get(RecordKind.OPERATION, identity) is None)
            rows = _rows(tx)
            data['sequence'] = max((r.payload['sequence'] for r in rows), default=0)+1
            tx.insert(StoredRecord(RecordKind.OPERATION, identity, self.ledger.scope, 1, data))
        self.ledger._run(self.binding.principal, Capability.COMMIT, write)
        return identity

    def change(self, request, state, *, result=None, http_status=None, error_code=None):
        require(state in STATES and state != 'ADMITTED')
        identity = 'meta-api-attempt-'+request.digest
        def write(tx):
            row = tx.get(RecordKind.OPERATION, identity)
            require(row is not None and row.payload.get('schema') == KIND)
            data = plain(row.payload)
            require(data['binding'] == request.public_binding()
                and data['warrant_digest'] == self.binding.warrant.digest())
            before = data['state'].removeprefix(KIND+':')
            require(before in ('ADMITTED', 'IN_FLIGHT') or before == 'COMPLETED' and state == 'UNKNOWN')
            require(state != 'IN_FLIGHT' or before == 'ADMITTED')
            if result is not None:
                require(state == 'COMPLETED' and result.request_digest == request.digest)
                receipt = result.receipt()
                receipt.update(attempt_id=identity, attempt=1, policy_epoch=data['policy_epoch'],
                               warrant_digest=data['warrant_digest'], nonce_digest=data['nonce_digest'])
                tx.insert(StoredRecord(RecordKind.RECEIPT, 'meta-api-'+request.digest,
                                      self.ledger.scope, 1, receipt))
            data.update(state=KIND+':'+state, http_status=http_status, error_code=error_code)
            tx.replace(StoredRecord(RecordKind.OPERATION, identity, self.ledger.scope,
                                   row.revision+1, data), expected_revision=row.revision)
        self.ledger._run(self.binding.principal, Capability.COMMIT, write)


class MetaReceiptView:
    """Read-only Core projection; abandoned pending records remain UNKNOWN."""
    def __init__(self, ledger, *, governor=None, source_reader):
        require(type(ledger) is CoreWarrantLedger and callable(source_reader))
        if governor is not None:
            from runtime.mission.governor import CoreDualGovernor
            require(type(governor) is CoreDualGovernor and governor.core is ledger.core
                    and governor.runner is ledger.runner and governor.policy.scope == ledger.scope)
        self.ledger, self.governor, self.source_reader = ledger, governor, source_reader

    def snapshot(self, *, active_attempt_id=None):
        output = {'call_state': 'NOT_ATTEMPTED', 'last_live_receipt': None, 'last_attempt': None,
            'billing_status': 'UNVERIFIED', 'credits_confirmed': False,
            'cost_estimate': None, 'settled_cost': None, 'budget_ledger_state': None}
        try:
            reader = self.ledger.core.local_operator(Capability.READ)
            def read(tx):
                rows = _rows(tx)
                if not rows: return None, None, None
                row = max(rows, key=lambda r:r.payload['sequence'])
                approval = tx.get(RecordKind.OPERATION, row.payload['approval_record_id'])
                require(approval is not None)
                from lab.archaioa.warrant import EffectWarrant
                warrant = EffectWarrant.from_dict(plain(approval.payload)['active'])
                _, approval_data, active = self.ledger._load(tx, warrant)
                return row, tx.get(RecordKind.RECEIPT, 'meta-api-'+row.payload['request_digest']), (active, approval_data)
            row, receipt, approval = self.ledger._run(reader, Capability.READ, read)
            if row is None: return output
            data = plain(row.payload)
            output.update(call_state='UNKNOWN', cost_estimate=data['cost_estimate'])
            binding = data['binding']
            require(data['attempt'] == 1 and data['state'] in FILTER
                and row.record_id == data['attempt_id'] == 'meta-api-attempt-'+data['request_digest']
                and binding['owner_scope_digest'] == canonical_sha256(self.ledger.scope)
                and binding['model_id'] == 'muse-spark-1.3' and binding['provider_id'] == 'meta_model_api'
                and binding['model_id'] in reader.model_binding_ids
                and self.source_reader() == (binding['source_sha'], binding['capsule_digest'])
                and self.governor is not None)
            governor = self.governor.inspect(reader)
            entry = governor['reservations'].get(data['reservation_id'])
            require(governor['epoch'] == data['policy_epoch'] and entry is not None
                and entry['epoch'] == data['policy_epoch'] and entry['task_id'] == binding['task_id']
                and entry['provider_id'] == binding['provider_id'] and entry['model_id'] == binding['model_id']
                and entry['request_digest'] == data['operation_digest'])
            warrant, approval_data = approval
            require(warrant.digest() == data['warrant_digest']
                and canonical_sha256(warrant.nonce) == data['nonce_digest']
                and warrant.operation_hash == 'sha256:'+data['operation_digest']
                and warrant.task_id == binding['task_id'] and warrant.lease_epoch == data['policy_epoch'])
            state = data['state'].removeprefix(KIND+':')
            if state in ('ADMITTED', 'IN_FLIGHT') and active_attempt_id != data['attempt_id']:
                state = 'UNKNOWN'
            output.update(call_state=state, budget_ledger_state=entry['state'],
                last_attempt={k:data[k] for k in ('attempt_id','attempt','request_digest','policy_epoch',
                    'http_status','error_code','created_at')})
            if state == 'COMPLETED':
                require(receipt is not None)
                require(approval_data['consumption'] is not None and entry['state'] in ('UNKNOWN','COMMITTED'))
                value = plain(receipt.payload)
                require(value['schema'] == 'aioa.meta.api-receipt.v1'
                    and value['request_digest'] == data['request_digest'] and value['binding'] == binding
                    and value['policy_epoch'] == data['policy_epoch'] and value['attempt_id'] == data['attempt_id']
                    and value['attempt'] == 1 and value['warrant_digest'] == data['warrant_digest']
                    and value['nonce_digest'] == data['nonce_digest']
                    and value['model_id'] == binding['model_id'] and value['provider_id'] == binding['provider_id']
                    and value['environment'] == 'META_API_LIVE_VERIFIED' and value['live_verified'] is True)
                usage = value['usage']
                require(set(usage) == {'prompt_tokens','completion_tokens','total_tokens'}
                    and all(type(n) is int and n >= 0 for n in usage.values())
                    and usage['total_tokens'] == usage['prompt_tokens']+usage['completion_tokens']
                    and usage['prompt_tokens'] <= data['input_bound']
                    and usage['completion_tokens'] <= data['output_bound'])
                output['last_live_receipt'] = value
            return output
        except Exception:
            # No caller data or raw backend errors cross the diagnostic boundary.
            output.update(call_state='UNKNOWN', last_live_receipt=None, last_attempt=None,
                          diagnostic_error='META_RECEIPT_READBACK_UNKNOWN')
            return output
