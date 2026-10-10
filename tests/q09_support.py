"""Synthetic offline Q09 state and process faults; no target transport."""
from dataclasses import replace
from pathlib import Path
import os
import sys

from lab.archaioa.evidence import EvidenceRef
from lab.archaioa.outcome import Applied
from runtime.core_admission import Capability
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.memory_patch.persistence.ports import TransactionRunner
from runtime.mission.governor import CoreDualGovernor, GovernorPolicy, Limits, ReservationRequest
from runtime.mission.intent import CoreIntentJournal
from runtime.mission.liability import Reconciliation
from runtime.mission.warrant import CoreWarrantLedger, approval_digest
from nv03_support import DurableFactory, DurableTransaction
from test_dual_governor import core, SCOPE, MODEL
from lab_archaioa.test_warrant import WarrantTests


class Fixture:
    def __init__(self, path):
        self.core = core()
        self.runner = TransactionRunner(self.core, DurableFactory(Path(path)))
        original = WarrantTests().fixture()
        owner = canonical_sha256(SCOPE)
        self.operation = {'operation_class': 'write', 'target_fingerprint': original.target_fingerprint,
                          'expected_target_revision': original.expected_target_revision,
                          'payload': {'fixture_only': True, 'value': 1}}
        self.warrant = replace(original, owner_scope=owner, lease_epoch=1,
            money_reservation_id='paired-1', risk_reservation_id='paired-1',
            operation_hash='sha256:' + canonical_sha256(self.operation),
            authority_scope=replace(original.authority_scope, owner_scope=owner))
        self.warrant = replace(self.warrant, approval_digest=approval_digest(self.warrant))
        self.ledger = CoreWarrantLedger(self.core, self.runner, SCOPE, clock=lambda:self.warrant.issued_at)
        limits = Limits(100, 10)
        self.gov = CoreDualGovernor(self.core, self.runner,
            GovernorPolicy(SCOPE, 'q09-fixture', limits, limits, limits), clock=lambda:100)
        self.request = ReservationRequest('paired-1', self.warrant.task_id, 'fixture', MODEL,
                                           canonical_sha256(self.operation), 50, 5)
        self.journal = CoreIntentJournal(self.ledger, self.gov, verifier=self.verify)

    def p(self, purpose=Capability.COMMIT):
        return self.core.local_operator(purpose)

    def init(self):
        self.gov.start_epoch(self.p(Capability.MANAGE))
        self.ledger.approve(self.p(Capability.OWNER_APPROVAL), self.warrant)

    def start(self):
        return self.journal.start(self.p(), self.warrant, self.operation, self.request)

    def verify(self, operation):
        assert operation == self.operation
        receipt = EvidenceRef('q09-receipt', 'receipt', 'sha256:'+'d'*64, 'v1')
        readback = EvidenceRef('q09-readback', 'independent-readback', 'sha256:'+'e'*64, 'v1')
        return Reconciliation(self.warrant.operation_hash, Applied(receipt.evidence_id), receipt, readback)

    def inspect(self):
        return self.journal.inspect(self.p(Capability.READ), self.warrant)

    def close(self):
        self.runner.close(); self.core.close()


if __name__ == '__main__':
    mode, path = sys.argv[1:]
    fx = Fixture(path)
    try:
        if mode in ('crash-before-start', 'crash-after-start'):
            original = DurableTransaction.commit
            def crash(tx):
                if mode == 'crash-after-start':
                    original(tx)
                os._exit(75)
            DurableTransaction.commit = crash
            fx.start()
            raise AssertionError('expected process crash')
        elif mode == 'probe':
            result = fx.start()
            assert result['fixture_step_now'] is False
            assert fx.inspect()['outcome']['contract_type'] == 'Unknown'
            assert fx.gov.inspect(fx.p(Capability.READ))['reservations']['paired-1']['state'] == 'UNKNOWN'
            print('FRESH_PROCESS_Q09_UNKNOWN_NO_REPLAY')
        elif mode == 'reconcile':
            epoch = fx.gov.start_epoch(fx.p(Capability.MANAGE))
            fx.journal.reconcile(fx.p(), fx.warrant, epoch)
            assert fx.inspect()['outcome']['contract_type'] == 'Applied'
            assert fx.journal.delivery(fx.p(Capability.READ), fx.warrant)['grants_replay'] is False
            print('FRESH_PROCESS_Q09_READBACK_ONLY')
        else:
            raise AssertionError('unknown fixture mode')
    finally:
        fx.close()
